import type { FaceView, Photo } from '../../api/types';
import { photoUrl } from './model';

export default function PhotoViewer({
  selected,
  faces,
  subject,
  busy,
  running,
  previousPhoto,
  nextPhoto,
  position,
  total,
  onNavigate,
  onSelectSubject,
}: {
  selected: Photo;
  faces: FaceView;
  subject: number | null;
  busy: boolean;
  running: boolean;
  previousPhoto?: Photo;
  nextPhoto?: Photo;
  position: number;
  total: number;
  onNavigate: (photo: Photo) => void;
  onSelectSubject: (subject: number) => void;
}) {
  return (
    <div className="photo-viewer">
      <div className="image-stage">
        <div className="image-wrap">
          <img src={photoUrl(selected.id)} alt={selected.display_name} />
          {(faces.photos[selected.id] ?? []).map((face, index) => {
            const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = face.box;
            return (
              <button
                key={index}
                className={`face-box ${face.subject === subject ? 'chosen' : ''}`}
                aria-label={`Name detected face ${face.subject + 1}`}
                style={{
                  left: `${(100 * x1) / (selected.width || 1)}%`,
                  top: `${(100 * y1) / (selected.height || 1)}%`,
                  width: `${(100 * (x2 - x1)) / (selected.width || 1)}%`,
                  height: `${(100 * (y2 - y1)) / (selected.height || 1)}%`,
                }}
                disabled={busy || running}
                onClick={() => {
                  onSelectSubject(face.subject);
                }}
              >
                <span>{face.subject + 1}</span>
              </button>
            );
          })}
        </div>
      </div>
      <nav className="photo-navigation" aria-label="Photo navigation">
        <button
          type="button"
          disabled={busy || !previousPhoto}
          title={previousPhoto?.display_name}
          onClick={() => {
            if (previousPhoto) onNavigate(previousPhoto);
          }}
        >
          Previous photo
        </button>
        <span aria-label={`Photo ${position + 1} of ${total} in album`}>
          {position + 1} / {total}
        </span>
        <button
          type="button"
          disabled={busy || !nextPhoto}
          title={nextPhoto?.display_name}
          onClick={() => {
            if (nextPhoto) onNavigate(nextPhoto);
          }}
        >
          Next photo
        </button>
      </nav>
    </div>
  );
}
