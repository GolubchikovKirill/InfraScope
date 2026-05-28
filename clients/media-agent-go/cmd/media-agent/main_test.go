package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestFetchManifestSendsTokenAndParsesDisabledState(t *testing.T) {
	const deviceID = "00000000-0000-0000-0000-000000000001"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/clients/"+deviceID+"/manifest" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if got := r.Header.Get("X-Media-Client-Token"); got != "secret" {
			t.Fatalf("unexpected token header: %q", got)
		}
		_ = json.NewEncoder(w).Encode(Manifest{
			DeviceID: deviceID,
			Revision: 0,
			Enabled:  false,
		})
	}))
	defer server.Close()

	manifest, err := fetchManifest(context.Background(), server.URL, deviceID, "secret")
	if err != nil {
		t.Fatalf("fetchManifest returned error: %v", err)
	}
	if manifest.Enabled {
		t.Fatal("disabled manifest should stay disabled")
	}
	if manifest.Revision != 0 {
		t.Fatalf("unexpected revision: %d", manifest.Revision)
	}
}

func TestSendHeartbeatReportsRevisionAndPlayerError(t *testing.T) {
	const deviceID = "00000000-0000-0000-0000-000000000001"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/clients/"+deviceID+"/heartbeat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if got := r.Header.Get("Content-Type"); got != "application/json" {
			t.Fatalf("unexpected content type: %q", got)
		}
		if got := r.Header.Get("X-Media-Client-Token"); got != "secret" {
			t.Fatalf("unexpected token header: %q", got)
		}

		var heartbeat Heartbeat
		if err := json.NewDecoder(r.Body).Decode(&heartbeat); err != nil {
			t.Fatalf("invalid heartbeat payload: %v", err)
		}
		if heartbeat.CurrentRevision == nil || *heartbeat.CurrentRevision != 9 {
			t.Fatalf("unexpected revision: %#v", heartbeat.CurrentRevision)
		}
		if heartbeat.PlayerState != "error" {
			t.Fatalf("unexpected state: %s", heartbeat.PlayerState)
		}
		if heartbeat.ErrorMessage == "" {
			t.Fatal("expected player error to be reported")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	revision := 9
	err := sendHeartbeat(context.Background(), server.URL, deviceID, "secret", Heartbeat{
		AgentVersion:    agentVersion,
		Hostname:        "hall-nettop-01",
		CurrentRevision: &revision,
		PlayerState:     "error",
		ErrorMessage:    "mpv executable file not found",
	})
	if err != nil {
		t.Fatalf("sendHeartbeat returned error: %v", err)
	}
}

func TestLoadConfigReadsWindowsAgentSettings(t *testing.T) {
	path := filepath.Join(t.TempDir(), "media-agent.json")
	err := os.WriteFile(path, []byte(`{
		"server": "http://10.10.98.10:8014",
		"device_id": "00000000-0000-0000-0000-000000000001",
		"token": "secret",
		"player": "C:\\Program Files\\mpv\\mpv.exe",
		"interval_seconds": 15
	}`), 0o600)
	if err != nil {
		t.Fatalf("write config: %v", err)
	}

	config, err := loadConfig(path)
	if err != nil {
		t.Fatalf("loadConfig returned error: %v", err)
	}

	if config.Server != "http://10.10.98.10:8014" {
		t.Fatalf("unexpected server: %s", config.Server)
	}
	if config.DeviceID == "" {
		t.Fatal("expected device id from config")
	}
	if got := resolveInterval(0, config); got != 15*time.Second {
		t.Fatalf("unexpected interval: %s", got)
	}
}

func TestResolveSourceURLUsesMediaServiceForRelativeAssetPath(t *testing.T) {
	got := resolveSourceURL("http://10.10.98.10:8014/", "/assets/abc/file")
	if got != "http://10.10.98.10:8014/assets/abc/file" {
		t.Fatalf("unexpected resolved URL: %s", got)
	}

	external := resolveSourceURL("http://10.10.98.10:8014", "http://cdn.local/video.mp4")
	if external != "http://cdn.local/video.mp4" {
		t.Fatalf("external URL should stay unchanged: %s", external)
	}
}
