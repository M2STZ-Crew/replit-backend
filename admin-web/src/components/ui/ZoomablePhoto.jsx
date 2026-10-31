import { useState } from 'react';

import ImageViewer from './ImageViewer.jsx';

/* A photo that opens full screen to zoom into ([ImageViewer]) when clicked.
 * Closing the viewer puts focus back on the photo. */
export default function ZoomablePhoto({ src, alt, caption = null, className = '', imageClassName = '' }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className={`rpl-photo-button ${className}`.trim()}
        onClick={() => setOpen(true)}
        aria-label={`Open ${alt} to zoom in`}
      >
        <img className={imageClassName} src={src} alt="" />
      </button>
      {open && <ImageViewer src={src} alt={alt} caption={caption} onClose={() => setOpen(false)} />}
    </>
  );
}
