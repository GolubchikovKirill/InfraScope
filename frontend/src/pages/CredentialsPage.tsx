// The credential vault and the password generator; the pieces live in components/credentials.
import { VaultSection } from "../components/credentials/VaultSection";
import { GeneratorSection } from "../components/credentials/PasswordGenerator";

export default function CredentialsPage() {
  return (
    <div className="space-y-6">
      <VaultSection />
      <GeneratorSection />
    </div>
  );
}
