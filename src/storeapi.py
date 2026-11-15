"""Microsoft Store integration (only active in the MSIX/Store build): trial licence and Share target.

Outside the Store package the app is treated as fully licensed.
"""
import asyncio
import os
import shutil
import time

import core

STORE_PRODUCT_ID = os.environ.get("SD_STORE_ID", "")  # filled in by the Store build (packaging/store.json)
try:
    import _storeid  # written by build_msix.py
    STORE_PRODUCT_ID = STORE_PRODUCT_ID or _storeid.STORE_PRODUCT_ID
except ImportError:
    pass


def _run(coro):
    return asyncio.run(coro)


class License:
    def __init__(self, state, days_left=None):
        self.state = state          # "full" | "trial" | "expired"
        self.days_left = days_left

    @property
    def locked(self):
        return self.state == "expired"


def check_license():
    if os.environ.get("SD_FAKE_LICENSE"):  # testing: "trial:5" or "expired"
        kind, _, days = os.environ["SD_FAKE_LICENSE"].partition(":")
        return License(kind, int(days) if days else None)
    if not core.PACKAGED:
        return License("full")
    try:
        from winrt.windows.services.store import StoreContext

        async def go():
            return await StoreContext.get_default().get_app_license_async()

        lic = _run(go())
        if not lic.sku_store_id:  # sideloaded / developer install
            return License("full")
        if lic.is_active and not lic.is_trial:
            return License("full")
        if lic.is_active and lic.is_trial:
            remaining = lic.trial_time_remaining
            secs = remaining.total_seconds() if hasattr(remaining, "total_seconds") else 0
            return License("trial", max(0, int((secs + 86399) // 86400)))
        return License("expired")
    except Exception:
        return License("full")  # never punish the user for a Store hiccup


def open_store_page():
    if STORE_PRODUCT_ID:
        os.startfile(f"ms-windows-store://pdp/?productid={STORE_PRODUCT_ID}")
    else:
        os.startfile("ms-windows-store://search/?query=ShrinkDrop")


class LicenseWatcher:
    def __init__(self):
        self.license = License("full")
        self.last = 0

    def refresh(self, force=False):
        if force or time.time() - self.last > (20 if self.license.locked else 600):
            self.last = time.time()
            self.license = check_license()
        return self.license


def take_share():
    """If Windows launched us from the Share menu, return the shared file paths; else None."""
    if not core.PACKAGED:
        return None
    try:
        from winrt.windows.applicationmodel import AppInstance
        from winrt.windows.applicationmodel.activation import ActivationKind, ShareTargetActivatedEventArgs
        from winrt.windows.applicationmodel.datatransfer import StandardDataFormats
        args = AppInstance.get_activated_event_args()
        if args is None or args.kind != ActivationKind.SHARE_TARGET:
            return None
        op = ShareTargetActivatedEventArgs._from(args).share_operation
        data = op.data

        async def read():
            paths = []
            if data.contains(StandardDataFormats.storage_items):
                os.makedirs(core.TEMP_DIR, exist_ok=True)
                for item in await data.get_storage_items_async():
                    p = item.path
                    volatile = (not p) or any(s in p.lower() for s in ("\\temp\\", "\\appdata\\local\\packages\\"))
                    if not volatile:
                        paths.append(p)
                        continue
                    # Shared from an app (e.g. Photos): keep a copy, results go to Pictures\ShrinkDrop.
                    dest = core.unique_path(os.path.join(core.TEMP_DIR, item.name))
                    if p and os.path.isfile(p):
                        shutil.copy2(p, dest)
                    else:
                        from winrt.windows.storage import StorageFile, StorageFolder, NameCollisionOption
                        folder = await StorageFolder.get_folder_from_path_async(core.TEMP_DIR)
                        copied = await StorageFile._from(item).copy_async(
                            folder, os.path.basename(dest), NameCollisionOption.GENERATE_UNIQUE_NAME)
                        dest = copied.path
                    paths.append(dest)
            return paths

        paths = _run(read())
        op.report_completed()
        return paths
    except Exception:
        return None
