import type { Schema } from '../api/types';

export default function SavedAlbums({
  albums,
  onNew,
  onOpen,
}: {
  albums: Schema['BatchSummary'][];
  onNew: () => void;
  onOpen: (id: string) => void;
}) {
  return (
    <>
      <div className="title-row">
        <div>
          <h1>Saved albums</h1>
          <p>Pick up a review where you left it.</p>
        </div>
        <button className="primary" onClick={onNew}>
          New batch
        </button>
      </div>
      {!albums.length ? (
        <div className="empty">
          <h2>Your first album starts here</h2>
          <p>Import photos and a competition roster, then analyze and review the captions.</p>
          <button onClick={onNew}>Import a batch</button>
        </div>
      ) : (
        <div className="album-list">
          {albums.map((album) => (
            <button className="album-row" key={album.id} onClick={() => onOpen(album.id)}>
              <div>
                <h2>{album.name}</h2>
                <span>Saved {new Date(album.updated_at).toLocaleString()}</span>
              </div>
              <span>{album.photo_count} photos</span>
              <span aria-hidden="true">→</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
