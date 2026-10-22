/* One glyph of the pass 6 icon set (REPLIT (MAIN) 04 · Icon: Material Symbols
 * Rounded, Fill 1, weight 400). The SVGs in public/icons are the Figma
 * exports, unedited; each is drawn as a CSS mask so the glyph takes the colour
 * of the text around it — the sidebar's icon/secondary, an active item's
 * bright white — without a copy per colour.
 *
 * Decorative by default. Pass `label` when the icon is the only thing that
 * says what a control does. */
export default function Icon({ name, size = 20, label, className = '' }) {
  return (
    <span
      className={`ad-icon${className ? ` ${className}` : ''}`}
      style={{ '--ad-icon': `url(/icons/${name}.svg)`, width: size, height: size }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : 'true'}
    />
  );
}
