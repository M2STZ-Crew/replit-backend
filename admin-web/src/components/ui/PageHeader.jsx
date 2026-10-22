export default function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
  titleId,
  className = '',
}) {
  return (
    <header className={`web-page-header ${className}`.trim()}>
      <div className="web-page-header-copy">
        {eyebrow && <p className="web-eyebrow">{eyebrow}</p>}
        <h1 className="web-page-title" id={titleId}>{title}</h1>
        {description && <p className="web-page-description">{description}</p>}
      </div>
      {actions && <div className="web-page-header-actions">{actions}</div>}
      {children && <div className="web-page-header-content">{children}</div>}
    </header>
  );
}
