/**
 * CommonCreed brand tokens — TypeScript mirror of `scripts/branding.py`.
 *
 * Source of truth: the Python module. These constants are copied (not
 * imported) because the Remotion renderer runs inside a Node container
 * that has no access to the Python sidecar's filesystem. If you change a
 * value here, change it in `scripts/branding.py` too — and vice versa.
 *
 * Palette origin: CommonCreed wordmark + MEMORY.md
 * (project_commoncreed_brand_palette.md).
 */

export const NAVY = "#1E3A8A" as const;
export const SKY_BLUE = "#5C9BFF" as const;
export const WHITE = "#FFFFFF" as const;

/**
 * Font family string as resolved by fontconfig inside the container.
 * The Dockerfile copies `assets/fonts/Inter-*.ttf` into
 * `/usr/local/share/fonts/commoncreed/` and runs `fc-cache -f`.
 */
export const BRAND_FONT_FAMILY =
  "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" as const;
