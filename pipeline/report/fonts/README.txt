The face the drawn board is rendered with, when one is supplied.

board_image.FONT_LADDER tries `fonts/board.ttf` before anything installed on
the machine, and that order is the whole point: a font found on the machine is
whatever that machine happens to have, while a font shipped beside the renderer
is the same one everywhere. Two runs of the drawn board match only if they
matched on the face.

Nothing is committed here. The brand's own face is licensed and this repository
may not carry it, so the slot is left open rather than filled with a substitute
that would quietly become the standard. Drop a licensed `board.ttf` in beside
this file and the ladder picks it up with no code change.

Without it the ladder falls through to Helvetica Neue, Arial or DejaVu Sans in
that order, and `FontChoice.graded` reports whether the face it found carries
the brand's weight ladder or only one weight. A board drawn on a single-weight
face is still correct; its hierarchy is carried by size alone.
