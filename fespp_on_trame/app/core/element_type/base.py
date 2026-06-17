"""`ElementType` — the base contract + neutral defaults.

Subclasses set ``KINDS`` (the runtime kinds they match) and override only
what deviates from their family default. The golden rule when adding
behaviour: write it at the HIGHEST level where it is correct, and never
higher — true for everything → here; true for a family → the family class;
true for one type → the unit class."""

from .enums import (
    TreeRole, VisibilityPolicy, ColorPolicy, EYE_REP, BUCKET_REP,
)


class ElementType:
    """Base contract. Defaults are a NEUTRAL standard rep — the base is only
    hit directly by the unknown-kind fallback; every concrete family
    (Grouping / Representation / Leaf) sets its own defaults."""

    #: runtime kind strings this class matches (set on concrete classes)
    KINDS: tuple = ()

    @classmethod
    def matches(cls, kind: str) -> bool:
        return kind in cls.KINDS

    # --- Tree role -------------------------------------------------------
    def tree_role(self) -> TreeRole:
        return TreeRole.REPRESENTATION

    def is_grouping(self) -> bool:
        """Folder that renders a tri-state checkbox + bulk-selects its
        descendants. NOTE: orthogonal to owning a source — a FrameRep is a
        grouping-for-the-tree yet a representation-for-the-source."""
        return False

    def propagates_selection(self) -> bool:
        """Checking the node selects every selectable descendant."""
        return self.is_grouping()

    def is_selectable(self) -> bool:
        """False only for Partial stubs (Title + UUID, no data)."""
        return True

    def is_ijk_grid(self) -> bool:
        """True only for the IJK reservoir grid (the modal slicer/volume
        pipeline). Lets the engine / legacy registry branch on the pipeline
        kind without a literal ``kind == 'IjkGrid'`` compare."""
        return False

    def is_channel_frame(self) -> bool:
        """True only for the wellbore LOG frame (`ChannelFrameRep`, kind
        'Frame'): a folder-for-the-tree whose renderable content is the
        single selected channel tube. Used to detect a log channel
        (array under such a frame) and to treat the frame's eye as a plain
        show/hide. NOT a marker frame."""
        return False

    def is_property(self) -> bool:
        """True only for a data-array PROPERTY leaf (`PropertyLeaf`: the
        Continuous / Discrete / Categorical / TimeSeries / MultiRealization
        / MultiRealizationTimeSeries kinds). Replaces the scattered
        ``'Property' in kind or kind in ('TimeSeries', 'MultiRealization',
        …)`` classification — a property leaf colours its parent rep, it is
        not a rep itself."""
        return False

    def eye_descriptor(self):
        """The eye affordance (a singleton EyeDescriptor), or None when the
        node carries no eye (groupings, frames — their children carry it)."""
        return EYE_REP

    # --- Tracking (data_load buckets) -----------------------------------
    def tracking_bucket(self):
        """Which ``ui_loaded_*`` list this kind feeds: BUCKET_REP /
        BUCKET_ARRAY / BUCKET_MARKER, or None (groupings / frames)."""
        return BUCKET_REP

    # --- Source / pipeline (rep_in_scene) -------------------------------
    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.STANDARD

    def color_policy(self) -> ColorPolicy:
        return ColorPolicy.COLORABLE

    def primary_hidden(self) -> bool:
        """True iff the rep's PRIMARY per-view extractor must stay hidden
        (frames: children render via their own per-child extractors)."""
        return False

    # --- Child management (frames: channels / markers) ------------------
    # Default no-ops — only FrameRep subclasses own children. `ris` is the
    # RepInScene: it keeps the per-(rep, view) state, the stateless singleton
    # reads/writes it. Per-type behaviour (exclusive log vs multi marker)
    # lives in those overrides.

    def set_child_visible(self, ris, child_path, visible):
        """Show/hide one child partition (channel/marker) in the rep's view."""
        return None

    def child_source(self, ris, child_path, create=False):
        """The per-(child, view) extractor for `child_path` (materialised
        hidden when `create`), or None."""
        return None

    def visible_child_source(self, ris):
        """The single SHOWN child extractor (one-at-a-time frames), or None."""
        return None

    def visible_child_displays(self, ris):
        """Display proxies of every shown child (SolidColor fan-out target)."""
        return []

    def set_child_color(self, ris, child_path, color_hex):
        """Tint one shown child's display."""
        return None

    # --- Visibility (per-view, called only on reps) ---------------------
    # The shared guards (view-None, per-view eye-chip) stay in RepInScene;
    # only the per-type policy lives here. Base = no-op (groupings/leaves
    # never have a per-view source).

    def refresh_primary_visibility(self, ris):
        """Re-assert the rep's PRIMARY source show/hide in ris.scene.pv_view."""
        return None

    def hide_in_view(self, ris):
        """Hide this rep's per-view pipeline in ris.scene.pv_view."""
        return None

    # --- Source construction --------------------------------------------
    # `ensure_source` returns the HEAD proxy ColorBy/display use; the actual
    # per-(rep, view) proxy is built by the strategy and STORED on `ris`
    # (ris._extractor / ris._per_view_ijk). Base = no source.

    def ensure_source(self, ris):
        """The head proxy used by ColorBy + the display layer."""
        return None

    def ensure_extractor(self, ris):
        """The standard per-view EnergisticsExtractor (non-IJK reps), or
        None. IjkGridRep overrides to None (it uses the IjkGrid pipeline)."""
        return None

    def ensure_per_view_ijk(self, ris):
        """The per-(rep, view) IjkGrid pipeline, or None. Only IjkGridRep
        builds one."""
        return None

    def rendered_sources(self, ris):
        """The per-view proxies this rep RENDERS into a view (the
        visibility-toggle / hide set). Returns a list, or None to fall
        through to the legacy registry lookup in source_resolver."""
        return None

    def color_sources(self, ris):
        """The per-view proxies ColorBy fans onto for this rep (excluding
        the clip output, which source_resolver appends). Returns a list, or
        None to fall through to the legacy registry lookup."""
        return None

    def array_candidate_source(self, ris, array_path):
        """The per-view source that CARRIES `array_path`'s VTK array (for
        COE / LUT array-name resolution). Default = None; Representation
        uses the primary extractor, ChannelFrameRep the channel's own."""
        return None

    def __repr__(self) -> str:
        kinds = ",".join(self.KINDS) if self.KINDS else "-"
        return f"<{type(self).__name__} kinds=[{kinds}]>"
