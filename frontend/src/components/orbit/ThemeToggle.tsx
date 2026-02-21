import { useTheme } from "next-themes";
import { Laptop, Moon, Sun } from "lucide-react";

const THEME_CYCLE = ["dark", "light", "system"] as const;
type ThemeCycle = (typeof THEME_CYCLE)[number];

function nextTheme(current: string | undefined): ThemeCycle {
  const idx = THEME_CYCLE.indexOf((current as ThemeCycle) ?? "system");
  return THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
}

export default function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme();

  // `theme` is the user's selection; `resolvedTheme` is the actual applied theme.
  const selection = (theme ?? "system") as ThemeCycle;
  const applied = resolvedTheme ?? "dark";

  const Icon = selection === "system" ? Laptop : applied === "dark" ? Moon : Sun;
  const label =
    selection === "system"
      ? "Theme: System"
      : applied === "dark"
        ? "Theme: Dark"
        : "Theme: Light";

  return (
    <button
      type="button"
      onClick={() => setTheme(nextTheme(theme))}
      className="glass-panel p-1.5 rounded-md hover:bg-white/10 transition-colors"
      aria-label={label}
      title={label}
    >
      <Icon className="w-4 h-4 text-primary" />
    </button>
  );
}

