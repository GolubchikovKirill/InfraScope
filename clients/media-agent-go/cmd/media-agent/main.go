package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

const agentVersion = "0.2.0"

type Manifest struct {
	DeviceID     string `json:"device_id"`
	Revision     int    `json:"revision"`
	Enabled      bool   `json:"enabled"`
	Title        string `json:"title"`
	MediaType    string `json:"media_type"`
	SourceURL    string `json:"source_url"`
	PlaybackMode string `json:"playback_mode"`
	Volume       *int   `json:"volume"`
}

type Heartbeat struct {
	AgentVersion    string `json:"agent_version,omitempty"`
	Hostname        string `json:"hostname,omitempty"`
	CurrentRevision *int   `json:"current_revision,omitempty"`
	PlayerState     string `json:"player_state"`
	ErrorMessage    string `json:"error_message,omitempty"`
}

type Config struct {
	Server          string `json:"server"`
	DeviceID        string `json:"device_id"`
	Token           string `json:"token"`
	Player          string `json:"player"`
	IntervalSeconds int    `json:"interval_seconds"`
}

type PlayerProcess struct {
	cmd  *exec.Cmd
	done chan error
}

func loadConfig(path string) (Config, error) {
	if strings.TrimSpace(path) == "" {
		return Config{}, nil
	}
	body, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return Config{}, nil
		}
		return Config{}, err
	}
	var config Config
	if err := json.Unmarshal(body, &config); err != nil {
		return Config{}, err
	}
	return config, nil
}

func defaultConfigPath() string {
	exePath, err := os.Executable()
	if err == nil {
		return filepath.Join(filepath.Dir(exePath), "media-agent.json")
	}
	return "media-agent.json"
}

func firstValue(values ...string) string {
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			return trimmed
		}
	}
	return ""
}

func resolveInterval(flagValue time.Duration, config Config) time.Duration {
	if flagValue > 0 {
		return flagValue
	}
	if envValue := strings.TrimSpace(os.Getenv("MEDIA_POLL_INTERVAL_SECONDS")); envValue != "" {
		seconds, err := time.ParseDuration(envValue + "s")
		if err == nil && seconds > 0 {
			return seconds
		}
	}
	if config.IntervalSeconds > 0 {
		return time.Duration(config.IntervalSeconds) * time.Second
	}
	return 10 * time.Second
}

func resolveSourceURL(baseURL, sourceURL string) string {
	source := strings.TrimSpace(sourceURL)
	if strings.HasPrefix(source, "/") {
		return strings.TrimRight(baseURL, "/") + source
	}
	return source
}

func (player *PlayerProcess) exited() (bool, error) {
	if player == nil {
		return true, nil
	}
	select {
	case err := <-player.done:
		return true, err
	default:
		return false, nil
	}
}

func fetchManifest(ctx context.Context, baseURL, deviceID, token string) (Manifest, error) {
	url := strings.TrimRight(baseURL, "/") + "/clients/" + deviceID + "/manifest"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return Manifest{}, err
	}
	if token != "" {
		req.Header.Set("X-Media-Client-Token", token)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return Manifest{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return Manifest{}, fmt.Errorf("manifest status %d", resp.StatusCode)
	}

	var manifest Manifest
	if err := json.NewDecoder(resp.Body).Decode(&manifest); err != nil {
		return Manifest{}, err
	}
	return manifest, nil
}

func sendHeartbeat(ctx context.Context, baseURL, deviceID, token string, heartbeat Heartbeat) error {
	url := strings.TrimRight(baseURL, "/") + "/clients/" + deviceID + "/heartbeat"
	body, err := json.Marshal(heartbeat)
	if err != nil {
		return err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("X-Media-Client-Token", token)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return fmt.Errorf("heartbeat status %d", resp.StatusCode)
	}
	return nil
}

func stopProcess(player *PlayerProcess) {
	if player == nil || player.cmd == nil || player.cmd.Process == nil {
		return
	}
	_ = player.cmd.Process.Signal(syscall.SIGTERM)
	select {
	case <-player.done:
	case <-time.After(3 * time.Second):
		_ = player.cmd.Process.Kill()
		<-player.done
	}
}

func startPlayer(ctx context.Context, playerBin string, baseURL string, manifest Manifest) (*PlayerProcess, error) {
	args := []string{"--fullscreen"}
	if manifest.PlaybackMode == "loop" || manifest.PlaybackMode == "" {
		args = append(args, "--loop")
	}
	if manifest.Volume != nil {
		args = append(args, fmt.Sprintf("--volume=%d", *manifest.Volume))
	}
	args = append(args, resolveSourceURL(baseURL, manifest.SourceURL))

	cmd := exec.CommandContext(ctx, playerBin, args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	player := &PlayerProcess{
		cmd:  cmd,
		done: make(chan error, 1),
	}
	go func() {
		player.done <- cmd.Wait()
	}()
	return player, nil
}

func main() {
	var (
		configPathFlag = flag.String("config", defaultConfigPath(), "path to media-agent.json")
		baseURLFlag    = flag.String("server", "", "media-service URL")
		deviceIDFlag   = flag.String("device-id", "", "InfraScope media player UUID")
		tokenFlag      = flag.String("token", "", "media client token")
		playerFlag     = flag.String("player", "", "player binary, for example mpv or vlc")
		intervalFlag   = flag.Duration("interval", 0, "manifest polling interval")
	)
	flag.Parse()

	config, err := loadConfig(*configPathFlag)
	if err != nil {
		log.Fatalf("config load failed: %v", err)
	}
	baseURL := firstValue(*baseURLFlag, os.Getenv("MEDIA_SERVICE_URL"), config.Server, "http://127.0.0.1:8014")
	deviceID := firstValue(*deviceIDFlag, os.Getenv("MEDIA_DEVICE_ID"), config.DeviceID)
	token := firstValue(*tokenFlag, os.Getenv("MEDIA_CLIENT_TOKEN"), config.Token)
	playerBin := firstValue(*playerFlag, os.Getenv("MEDIA_PLAYER_BIN"), config.Player, "mpv")
	interval := resolveInterval(*intervalFlag, config)

	if strings.TrimSpace(deviceID) == "" {
		log.Fatal("device-id is required")
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	var currentRevision = -1
	var playerProcess *PlayerProcess
	var playerState = "idle"
	var lastError string
	hostname, _ := os.Hostname()
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		manifest, err := fetchManifest(ctx, baseURL, deviceID, token)
		if err != nil {
			log.Printf("manifest fetch failed: %v", err)
			playerState = "error"
			lastError = err.Error()
		} else if manifest.Revision != currentRevision {
			currentRevision = manifest.Revision
			stopProcess(playerProcess)
			playerProcess = nil
			if manifest.Enabled && manifest.SourceURL != "" {
				next, err := startPlayer(ctx, playerBin, baseURL, manifest)
				if err != nil {
					log.Printf("player start failed: %v", err)
					playerState = "error"
					lastError = err.Error()
				} else {
					playerProcess = next
					playerState = "playing"
					lastError = ""
					log.Printf("playing revision %d: %s", manifest.Revision, manifest.SourceURL)
				}
			} else {
				playerState = "disabled"
				lastError = ""
				log.Printf("playback disabled, revision %d", manifest.Revision)
			}
		} else if playerProcess != nil {
			exited, playerErr := playerProcess.exited()
			if exited {
				playerProcess = nil
				playerState = "error"
				if playerErr != nil {
					lastError = playerErr.Error()
				} else {
					lastError = "player exited unexpectedly"
				}
				log.Printf("player exited: %s", lastError)
			} else {
				playerState = "playing"
				lastError = ""
			}
		} else if !manifest.Enabled {
			playerState = "disabled"
			lastError = ""
		}

		var appliedRevision *int
		if currentRevision >= 0 {
			appliedRevision = &currentRevision
		}
		if err := sendHeartbeat(ctx, baseURL, deviceID, token, Heartbeat{
			AgentVersion:    agentVersion,
			Hostname:        hostname,
			CurrentRevision: appliedRevision,
			PlayerState:     playerState,
			ErrorMessage:    lastError,
		}); err != nil {
			log.Printf("heartbeat failed: %v", err)
		}

		select {
		case <-ctx.Done():
			stopProcess(playerProcess)
			return
		case <-ticker.C:
		}
	}
}
