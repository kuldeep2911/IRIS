// Settings — avatar toggle (off => voice-only) + theme/info.
import { useStore } from "../store";

export default function Settings() {
  const { avatarEnabled, setAvatarEnabled } = useStore();
  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Settings</h1>

      <label className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 p-4">
        <input
          type="checkbox"
          checked={avatarEnabled}
          onChange={(e) => setAvatarEnabled(e.target.checked)}
          className="h-4 w-4 accent-iris-accent"
        />
        <span>
          <span className="font-medium">3D avatar (TalkingHead)</span>
          <span className="block text-xs text-gray-500">
            Show the lip-syncing IRIS face in Chat. Off = voice-only.
          </span>
        </span>
      </label>
    </div>
  );
}
