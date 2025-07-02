DROP TABLE IF EXISTS albums, artists, music, music_artists, collections, collection_children CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE albums (
	album_id SERIAL PRIMARY KEY ,
    album_name VARCHAR(255) NOT NULL,
	release_date DATE NOT NULL,
	img_path TEXT GENERATED ALWAYS AS ('albums/' || (album_id) || '.jpeg') STORED
);

CREATE TABLE artists (
	artist_id SERIAL PRIMARY KEY,
    artist_name VARCHAR(255) NOT NULL,
    artist_img BYTEA
);


CREATE TABLE music (
	music_id SERIAL PRIMARY KEY,
    music_name VARCHAR(255) NOT NULL,
    album_id INT NOT NULL,
    lyrics_by_timestamp JSONB,
    release_date DATE NOT NULL,
    duration REAL NOT NULL,
    isrc VARCHAR(255) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    downloaded_on TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (album_id) REFERENCES albums(album_id)
);

CREATE TABLE music_artists (
	music_id INT NOT NULL,
    artist_id INT NOT NULL,
    sort_order INT NOT NULL,
    PRIMARY KEY (music_id, artist_id),
    FOREIGN KEY (music_id) REFERENCES music(music_id),
	FOREIGN KEY (artist_id) REFERENCES artists(artist_id)
);

DROP MATERIALIZED VIEW IF EXISTS library_music_view;
CREATE MATERIALIZED VIEW library_music_view AS
SELECT
    m.*,
    al.album_name,
    al.img_path,
    ARRAY_AGG(ar.artist_id) AS artist_ids,
    ARRAY_AGG(ar.artist_name) AS artist_names,
    (COALESCE(music_name) || CHR(31) || COALESCE(album_name)) AS search_vector
FROM music AS m
LEFT JOIN albums AS al USING (album_id)
LEFT JOIN music_artists AS ma USING (music_id)
LEFT JOIN artists AS ar USING (artist_id)
GROUP BY m.music_id, al.album_id;

CREATE UNIQUE INDEX index ON library_music_view (music_id);
CREATE INDEX idx_library_search_gin ON library_music_view
USING GIN (search_vector gin_trgm_ops);
REFRESH MATERIALIZED VIEW CONCURRENTLY library_music_view;


CREATE TABLE collections (
    collection_id SERIAL PRIMARY KEY,
    type VARCHAR(25) NOT NULL,
    parent_collection_id INT,
    name VARCHAR(255) NOT NULL,
    created TIMESTAMPTZ NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL,
    last_played TIMESTAMPTZ,
    thumbnail BYTEA,
    protected BOOLEAN
);

CREATE TABLE collection_children (
    collection_id INT NOT NULL,
    music_id INT NOT NULL,
    added_on TIMESTAMPTZ NOT NULL,
    sort_order SERIAL,
    PRIMARY KEY (collection_id, music_id),
    FOREIGN KEY (collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY (music_id) REFERENCES music(music_id)
);

DROP MATERIALIZED VIEW IF EXISTS music_view;
CREATE MATERIALIZED VIEW music_view AS
SELECT lmv.*, a.artist_id, a.artist_name, ma.sort_order AS artist_order FROM library_music_view AS lmv
JOIN music_artists ma USING (music_id)
JOIN artists AS a USING (artist_id);
REFRESH MATERIALIZED VIEW music_view;
