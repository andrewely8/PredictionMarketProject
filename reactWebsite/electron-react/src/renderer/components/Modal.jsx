export default function Modal({ title, onClose, children, wide = false }) {
  return (
    <div className="modalBackdrop" role="dialog" aria-label={title}>
      <div
        className="modalBody"
        style={wide ? { width: 'min(1100px, 95vw)' } : undefined}
      >
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3>{title}</h3>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
