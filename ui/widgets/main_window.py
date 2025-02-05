import asyncio
import threading
from math import ceil
from random import randint
from gi.repository import Gtk, GLib, Gdk, Gio
from main import get_videos
from ui.widgets.duration_filters import DurationFilters
from ui.widgets.library_row import LibraryRow
from ui.widgets.header import Header
from ui.widgets.update_frame import UpdateFrame
from utils import CURRENT_VERSION
from utils.debounce import debounce

GLOBAL_SPACING = 20
added = False
ROW_COUNT = 3

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
PORTAL_SETTINGS_INTERFACE = "org.freedesktop.portal.Background"



# Window
# |
# ScrolledWindow (root_scroll) -> requires to have exactly 1 children
# |
# Box (main_container)
# |
# Entry (dummy_entry)
# Header (head)
# LibraryRow duplicated n times
# Spinner (spinner)
# Button (more_button)
# label (footer)


class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Steam Deck Repo Manager")
        default_width = 1180

        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(default_width, 680)
        self.current_page = 1

        # workaround for focus of first entry
        dummy_entry = Gtk.Entry()

        # Global Layout
        main_container = Gtk.Box()
        main_container.set_margin_top(GLOBAL_SPACING)
        main_container.set_margin_bottom(GLOBAL_SPACING)
        main_container.set_margin_left(GLOBAL_SPACING)
        main_container.set_margin_right(GLOBAL_SPACING)
        main_container.set_valign(Gtk.Align.START)
        main_container.set_orientation(Gtk.Orientation.VERTICAL)

        self.head = Header(on_search=self.on_search, on_duration_filter=self.on_duration_filter_click)
        main_container.add(dummy_entry)

        main_container.add(self.head)
        self.duration_filters = DurationFilters()
        main_container.add(self.duration_filters)

        self.update_frame = UpdateFrame()
        main_container.add(self.update_frame)

        root_scroll = Gtk.ScrolledWindow()
        root_scroll.add(main_container)

        self.add(root_scroll)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()
        self.head.hide()
        self.connect_bus()

        if not self.update_frame.should_update:
            self.update_frame.hide()

        self.rows_container = Gtk.Box()
        self.rows_container.set_margin_top(GLOBAL_SPACING)
        self.rows_container.set_valign(Gtk.Align.START)
        self.rows_container.set_orientation(Gtk.Orientation.VERTICAL)
        self.rows_container.show()
        main_container.add(self.rows_container)

        self.spinner = Gtk.Spinner()
        main_container.add(self.spinner)

        self.more_button = Gtk.Button(label="Load more")
        self.more_button.set_margin_bottom(GLOBAL_SPACING)
        self.more_button.connect('clicked', self.download_videos_and_apply_filters, {"paginate": True})
        main_container.add(self.more_button)

        self.footer = Gtk.Label(
            label=f"<span>Made with ♥ by Captain J. Sparrow built on top of <a href='https://steamdeckrepo.com/'>Steam Deck Repo</a>. Version <b>{CURRENT_VERSION}</b></span>")
        self.footer.set_use_markup(True)
        main_container.add(self.footer)

        # Dummy entry got focus, hide it now
        dummy_entry.destroy()
        self.download_videos_and_apply_filters()

    def on_videos_downloaded(self, videos, hide_pagination: bool = False):
        self.spinner.stop()
        self.head.show()  # Show clear video button
        self.footer.show()  # Show credits
        for i in range(ceil(len(videos) / ROW_COUNT)):
            row = LibraryRow(
                videos[i * ROW_COUNT:(i + 1) * ROW_COUNT],
                self.rows_container.get_allocated_width(), ROW_COUNT
            )
            sep = Gtk.Box()
            sep.set_margin_bottom(GLOBAL_SPACING)
            self.rows_container.add(row)
            self.rows_container.add(sep)
            sep.show()
            row.show_all()

            if len(videos) > 0:
                self.more_button.set_label("Load more")
                self.more_button.set_sensitive(True)
                self.more_button.show()
            if hide_pagination:
                self.more_button.hide()

    def download_videos_async(self, page: int, search: str = ''):
        videos = asyncio.run(get_videos(page, search))
        GLib.idle_add(self.on_videos_downloaded, videos, len(search) > 0)

    def download_videos_and_apply_filters(self, _=None, paginate: bool = False, search: str = ''):
        if paginate:
            self.more_button.set_label("Loading ...")
            self.more_button.set_sensitive(False)
            self.current_page = self.current_page + 1
        else:
            self.spinner.start()
            self.spinner.show()
            self.footer.hide()
            self.more_button.hide()
            self.current_page = 0

        threading.Thread(target=self.download_videos_async, daemon=True, kwargs={'page': self.current_page, "search": search}).start()

    @debounce(1)
    def on_search(self, value):
        # We need to put Gtk in right thread since debounce create a timer in a separate thread
        Gdk.threads_enter()
        self.more_button.hide()

        # Empty library
        for child in self.rows_container.get_children():
            child.destroy()

        self.download_videos_and_apply_filters(search=value)
        Gdk.threads_leave()

    def on_duration_filter_click(self, _):
        self.duration_filters.set_expanded(not self.duration_filters.get_expanded())

    def __receive_autostart(self, *args):
        state = args[5][0]
        autostart = args[5][1]['autostart']

        if state != 0:
            Gdk.threads_enter()
            dialog = Gtk.MessageDialog(
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="error requesting background",
            )
            dialog.run()
            dialog.destroy()
            Gdk.threads_leave()

    def connect_bus(self):
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None,
                                       PORTAL_BUS_NAME,
                                       PORTAL_OBJECT_PATH,
                                       PORTAL_SETTINGS_INTERFACE,
                                       None)
        token = 0 + randint(10000000, 90000000)
        options = {
            'handle_token': GLib.Variant(
                's', f'com/steamdeckrepo/manager/{token}'
            ),
            'reason': GLib.Variant('s', 'Steam deck repo abckground.'),
            'autostart': GLib.Variant('b', True),
            'commandline': GLib.Variant('as', ['python3', '/app/test.py']),
            'dbus-activatable': GLib.Variant('b', False)
        }
        request = proxy.RequestBackground('(sa{sv})', '', options)
        print(request)
        bus.signal_subscribe(
            'org.freedesktop.portal.Desktop',
            'org.freedesktop.portal.Request',
            'Response',
            request,
            None,
            Gio.DBusSignalFlags.NO_MATCH_RULE,
            self.__receive_autostart,
            None
        )
