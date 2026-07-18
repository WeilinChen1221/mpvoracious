# Mining History

Mining History captures subtitle moments for later sentence mining and supplies their contextual media to associated Anki notes.

## Language

**Mining History Record**:
A captured subtitle moment and its source context. One Mining History Record may be linked to multiple Anki Notes.
_Avoid_: Row, card

**Source Info**:
A stable, human-readable description of a Mining History Record's captured source, derived from its filename, path, episode, and timestamp according to the Capture Profile.
_Avoid_: MiscInfo, Notes field

**Capture Profile**:
The mpvoracious configuration profile active when a Mining History Record is created. Media Resend requires that profile and uses its current media-generation settings; an unavailable profile makes the resend fail without changing existing media.
_Avoid_: Active profile, worker profile

**Linked Anki Note**:
An existing Anki Note associated with a Mining History Record through sentence matching. Every linked note remains a target for later media correction; a note leaves the relationship only when Anki confirms that it no longer exists.
_Avoid_: Card, latest note

**Media Delivery**:
The latest attempt to provide one Mining History Record's audio and image to one Linked Anki Note. Each linked note has an independent Media Delivery outcome.
_Avoid_: Record result

**Media Target**:
The audio and image fields selected for a Linked Anki Note when that relationship is created. A Media Target remains stable even if configuration field names later change.
_Avoid_: Current media fields

**Media Resend**:
A user-requested, immediately executed regeneration and complete replacement of every Linked Anki Note's Media Target for one Mining History Record. It is the sole media-correction action, requires no confirmation, does not preserve prior content in those two fields, and does not modify sentence, secondary subtitle, MiscInfo, tags, or other fields.
_Avoid_: Retry

**Record Status**:
The aggregate Media Delivery state of a Mining History Record: **Waiting for Note** when it has no linked notes, **Sending Media** while media work is queued or running, **Media Ready** when every linked note succeeded, and **Media Failed** when at least one linked note failed.
_Avoid_: Latest-note status
