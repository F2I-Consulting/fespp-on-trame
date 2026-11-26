# trame-fespp-xmlviewer

One RESQML object, two ways: a readable tree (folded, filterable, paged
past 600 rows, a reference is a button that opens the object in an XML
explorer tab) and the raw text (highlighted as a token tree, never
`v-html`). Two components: `XmlBody` (the object) and `XmlViewer` (the
frame: the tabs — one navigation stack each —, the breadcrumb, the Tree |
Raw reading, Copy XML). Mounted both by the Attributes card (bare) and by
the XML explorer view (`framed`, wearing the panel frame with its title).
Props `xml`, `trail`, `tabs`, `activeTab`, `note`, `emptyLabel` (the
gesture that fills the empty state), `framed`, `hits` (the answer to the
last search: `{query, hits: [{uuid, title, type, partial}], total, note}`);
events `follow`, `back`, `select-tab`, `close-tab`, `new-tab`, `search`
(the find row, debounced) and `pick` (a found object). The framed viewer
is a view of its own: its find row lists the repository, so it opens on
any object without another view's gesture.
