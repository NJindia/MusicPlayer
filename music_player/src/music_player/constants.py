from datetime import UTC, datetime
from typing import Literal

MAIN_SPACING = 7
MAIN_PADDING = 7

TOOLBAR_HEIGHT = 100
TOOLBAR_MEDIA_CONTROL_WIDTH = 700
TOOLBAR_PADDING = 5
VOLUME_SLIDER_MAX_WIDTH = 200
RepeatState = Literal["NO_REPEAT", "REPEAT_QUEUE", "REPEAT_ONE"]

PLAYLIST_HEADER_PADDING = 5
PLAYLIST_HEADER_FONT_SIZE = 20

QUEUE_ENTRY_HEIGHT = 70
QUEUE_ENTRY_WIDTH = 388
QUEUE_ENTRY_SPACING = 6

QUEUE_WIDTH = 400
QUEUE_SPACING = 6


SKIP_BACK_SECOND_THRESHOLD = 5
"""Number of seconds into a track that pressing the rewind button will skip back to the previous track."""

MAX_SIDE_BAR_WIDTH = 450

MUSIC_IDS_MIMETYPE = "application/x-music-ids"

MIN_DATETIME = datetime(1970, 1, 1, tzinfo=UTC)

USER_ID = 1
