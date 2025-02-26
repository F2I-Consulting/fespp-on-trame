import base64
import contextlib
from pathlib import Path
from tempfile import mkdtemp
from typing import Literal
from urllib.parse import urlparse

import paraview.web.venv  # noqa: F401 # type: ignore # Needed to use ParaView with a venv
from trame.app import get_server
from trame.decorators import TrameApp
from trame_server import Server

from fespp_on_trame.app.core.mesh_engine import initialize_mesh_engine
from fespp_on_trame.app.io.http import download_file_from_url
from fespp_on_trame.app.ui.view import ui
from fespp_on_trame.constants import TRAME_APP_TITLE


def decode_url_base64(encoded_url):
    base64_bytes = encoded_url.encode('utf-8')
    url_bytes = base64.urlsafe_b64decode(base64_bytes)
    url = url_bytes.decode('utf-8')

    return url


@TrameApp()
class App:
    local_epc_file_path: Path
    remote_h5_file_location: str | None
    remote_epc_file_location: str | None
    h5_file_name: str | None
    mode: Literal["remote_file", "local_file"]

    def __init__(
        self,
        server=None,
        *,
        fespp_plugin_path: Path,
        slicing_plugin_path: Path,
        local_epc_file_path: Path,
        remote_h5_file_location: str | None,
        remote_epc_file_location: str | None,
        h5_file_name: str | None
    ):
        self.server = get_server(server, client_type="vue3")

        self.server.state.trame__title = TRAME_APP_TITLE

        self.local_epc_file_path = local_epc_file_path

        assert self.local_epc_file_path.exists()

        if remote_epc_file_location and remote_h5_file_location:
            assert h5_file_name is not None
            assert remote_epc_file_location != remote_h5_file_location
            self.remote_epc_file_location = decode_url_base64(remote_epc_file_location)
            self.remote_h5_file_location = decode_url_base64(remote_h5_file_location)
            self.h5_file_name = h5_file_name
            self.mode = "remote_file"
        else:
            self.mode = "local_file"

        initialize_mesh_engine(
            server,
            fespp_plugin_path=fespp_plugin_path,
            slicing_plugin_path=slicing_plugin_path,
        )


def server_ready(**state):
    print("FESPP on TRAME Ready", flush=True)
    print("+" * 4096, flush=True)


if __name__ == "__main__":
    app_server = get_server()

    app_server.cli.add_argument(
        "--local-epc-file-path",
        dest="local_epc_file_path",
        help="Path to epc file to display",
        type=Path,
    )
    app_server.cli.add_argument(
        "--remote-epc-file-location", dest="remote_epc_file_location"
    )
    app_server.cli.add_argument(
        "--remote-h5-file-location", dest="remote_h5_file_location"
    )
    app_server.cli.add_argument(
        "--h5filename", dest="h5_file_name"
    )
    app_server.cli.add_argument(
        "--fespp-plugin-path",
        dest="fespp_plugin_path",
        required=True,
        help="path to fespp paraview plugin .so",
        type=Path,
    )
    app_server.cli.add_argument(
        "--slicing-plugin-path",
        dest="slicing_plugin_path",
        required=True,
        help="path to slicing paraview plugin .so",
        type=Path,
    )

    if isinstance(app_server, Server):
        args, _ = app_server.cli.parse_known_args()
        app_server.controller.on_server_ready.add(server_ready)
        app = App(
            app_server,
            fespp_plugin_path=args.fespp_plugin_path,
            slicing_plugin_path=args.slicing_plugin_path,
            local_epc_file_path=args.local_epc_file_path,
            remote_h5_file_location=args.remote_h5_file_location if args.remote_h5_file_location != r"${remote_h5_file_location}" else None,
            remote_epc_file_location=args.remote_epc_file_location if args.remote_epc_file_location != r"${remote_epc_file_location}" else None,
            h5_file_name=args.h5_file_name if args.h5_file_name != r"${h5filename}" else None,
        )

        # Needed to define paraview view
        ui(app.server)

        epc_file_path = None

        if app.mode == "remote_file":
            with contextlib.ExitStack() as stack:
                temp_dir = mkdtemp()

                epc_file_name = urlparse(app.remote_epc_file_location).path.split("/")[
                    -1
                ]
                # h5_file_name = urlparse(app.remote_h5_file_location).path.split("/")[
                #     -1
                # ]

                if not epc_file_name.endswith(".epc"):
                    epc_file_name = f"{epc_file_name}.epc"

                # if not h5_file_name.endswith(".h5"):
                #     h5_file_name = f"{h5_file_name}.h5"

                h5_file_name = app.h5_file_name

                epc_file_handle = stack.enter_context(
                    open(f"{temp_dir}/{epc_file_name}", "wb+")
                )
                h5_file_handle = stack.enter_context(
                    open(f"{temp_dir}/{h5_file_name}", "wb+")
                )

                download_file_from_url(app.remote_epc_file_location, epc_file_handle)
                download_file_from_url(app.remote_h5_file_location, h5_file_handle)
                app_server.controller.load_epc_file(epc_file_handle.name)
        else:
            app_server.controller.load_epc_file(str(app.local_epc_file_path))

        app_server.controller.define_slicing_pipeline()

        ui(app.server)

        app.server.start()
