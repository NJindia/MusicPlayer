CREATE TABLE collection_base (
	collection_id INT NOT NULL AUTO_INCREMENT,
    collection_name VARCHAR(255) NOT NULL,
    PRIMARY KEY (collection_id)
);

CREATE TABLE albums (
	album_id INT NOT NULL AUTO_INCREMENT,
    album_name VARCHAR(255) NOT NULL,
	release_date DATE NOT NULL,
	cover_bytes MEDIUMBLOB,
    PRIMARY KEY (album_id)
);

CREATE TABLE artists (
	artist_id INT NOT NULL AUTO_INCREMENT,
    artist_name VARCHAR(255) NOT NULL,
    artist_img MEDIUMBLOB,
    PRIMARY KEY (artist_id)
);


CREATE TABLE music (
	music_id INT NOT NULL AUTO_INCREMENT,
    album_id INT NOT NULL,
    lyrics_by_timestamp JSON,
    release_date DATE NOT NULL,
    duration DATETIME NOT NULL,
    isrc VARCHAR(255) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    downloaded DATETIME NOT NULL,
    PRIMARY KEY (music_id),
    FOREIGN KEY (album_id) REFERENCES albums(album_id)
);

CREATE TABLE music_artists (
	music_id INT NOT NULL,
    artist_id INT NOT NULL,
    PRIMARY KEY (music_id, artist_id),
    FOREIGN KEY (music_id) REFERENCES music(music_id),
	FOREIGN KEY (artist_id) REFERENCES artists(artist_id)
);
