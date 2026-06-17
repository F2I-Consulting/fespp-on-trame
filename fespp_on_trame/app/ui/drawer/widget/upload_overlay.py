"""Full-drawer overlay shown during file upload.

Reads `state.upload_uploading` (visibility) and `state.upload_progress`
(0-100 percent, or 0 = indeterminate phase)."""
from trame.widgets import html, vuetify3


class UploadOverlay:
    """Renders the upload progress overlay covering the entire drawer."""

    def render(self):
        with html.Div(
            v_show="upload_uploading",
            style=(
                "position: absolute; inset: 0; z-index: 1001;"
                " background: rgba(0,0,0,0.55);"
                " display: flex; flex-direction: column;"
                " align-items: center; justify-content: center; gap: 16px;"
            ),
        ):
            vuetify3.VProgressCircular(
                indeterminate=("upload_progress === 0",),
                model_value=("upload_progress", 0),
                color="blue",
                size=64,
                width=6,
            )
            html.P(
                "{{ upload_progress > 0 ? 'Upload… ' + upload_progress + '%' : 'Uploading…' }}",
                style="color: white; font-size: 0.95rem; margin: 0;",
            )
