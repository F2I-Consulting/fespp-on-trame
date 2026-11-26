"""`ElementType`: the base contract and its neutral defaults.

Subclasses set ``KINDS`` (the runtime kinds they match) and override only
what deviates from their family default. The golden rule when adding
behaviour: write it at the HIGHEST level where it is correct, and never
higher — true for everything → here; true for a family → the family class;
true for one type → the unit class."""

from .enums import (
    TreeRole, VisibilityPolicy, ColorPolicy, EYE_REP, BUCKET_REP,
)


class ElementType:
    """Base contract, never instantiated directly.

    Defaults describe a NEUTRAL standard rep; every family (Grouping /
    Representation / Leaf) sets its own defaults, and the unknown-kind
    fallback is a plain Representation (see registry.py)."""

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
        pipeline). Lets callers branch on the pipeline kind without a
        literal ``kind == 'IjkGrid'`` compare."""
        return False

    def is_channel_frame(self) -> bool:
        """True only for the wellbore LOG frame (`ChannelFrameRep`, kind
        'Frame'): a folder-for-the-tree whose renderable content is the
        single selected channel tube. Used to detect a log channel
        (array under such a frame) and to treat the frame's eye as a plain
        show/hide. NOT a marker frame."""
        return False

    def is_property(self) -> bool:
        """True only for a data-array PROPERTY leaf (`PropertyLeaf` + its
        TimeSeries / MultiRealization subclasses: the Continuous / Discrete /
        Categorical / TimeSeries / MultiRealization / MultiRealizationTimeSeries
        kinds). Use it instead of classifying kind strings (``'Property' in
        kind or kind in ('TimeSeries', …)``): a property leaf colours its
        parent rep, it is not a rep itself."""
        return False

    def is_time_series(self) -> bool:
        """True for a time-series property leaf — the 'TimeSeries' and
        'MultiRealizationTimeSeries' kinds (the time slider applies)."""
        return False

    def is_multi_realization(self) -> bool:
        """True for a multi-realization property leaf — the 'MultiRealization'
        and 'MultiRealizationTimeSeries' kinds (the realization picker
        applies)."""
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

    # --- Child management (frames: channels / markers) ------------------
    # Default no-ops — only FrameRep subclasses own children. `ris` is the
    # RepInScene: it keeps the per-(rep, view) state, the stateless singleton
    # reads/writes it. Per-type behaviour (exclusive log vs multi marker)
    # lives in those overrides.

    # --- Visibility (per-view, called only on reps) ---------------------
    # The shared guards (view-None, per-view eye-chip) stay in RepInScene;
    # only the per-type policy lives here. Base = no-op (groupings/leaves
    # never have a per-view source).

    # --- Source construction --------------------------------------------
    # `ensure_source` returns the HEAD proxy ColorBy/display use; the actual
    # per-(rep, view) proxy is built by the strategy and STORED on `ris`
    # (ris._extractor / ris._per_view_ijk). Base = no source.

    def __repr__(self) -> str:
        kinds = ",".join(self.KINDS) if self.KINDS else "-"
        return f"<{type(self).__name__} kinds=[{kinds}]>"
