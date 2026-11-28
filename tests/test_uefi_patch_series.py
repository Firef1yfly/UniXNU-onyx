"""Series integrity of patches/uefi: the onyx firmware patch stack.

The series targets two trees, because the port has two:

* Mu-Silicium at `1d0f1e41018b2519ab9b41b60ac073453e346ba0` (the firmware tree
  that builds), and
* the external UniXNU checkout, which the Mu tree consumes through the
  untracked symlink `Mu-Silicium/UniXNUPkg -> ../UniXNU/package/UniXNUPkg`.

`UniXNUPkg` is not part of the Mu commit, so a Mu-only worktree has no pre-image
for the patches that target it: `git apply` there fails with "no such file".
Those patches must be applied to a tree that has the checkout mounted, at the
pristine UniXNU revision, and a Mu-Silicium tree without that mount is an
incomplete port tree rather than a broken patch. Which numbers go where is
pinned in TARGETS below.

The mount is also not an apply target. 0012 has to land in the UniXNU checkout
(`git -C <UniXNU> apply --directory=package`), because `git apply` refuses to
write through a symlink that leaves the work tree; the link exists for the
build, not for the patch. MOUNTS records the links the port tree needs and why,
so a rebuild from the series cannot silently lose one of them. Neither is a
patch: a patch may write *through* `UniXNUPkg`, but no patch creates the link.

Applying the series with `git apply` in file-name order only works when every
patch is generated from the content the previous one leaves behind. An earlier
revision failed exactly there: 0001, 0002 and 0007 all diffed the same
BootShim.S baseline blob. These tests pin the structural property and the
two-tree requirement; they do not apply the patches and they are not firmware
evidence.
"""
import os
import re
import tempfile
import unittest
from pathlib import Path

DEVICE = Path(__file__).resolve().parents[1]
UEFI = DEVICE / 'patches/uefi'

# Reviewed series, in application order. Numbers are not renumbered when a
# patch is removed; 0002-0006 were withdrawn (see the fold notes in 0007/0009).
SERIES = [
    '0001-bootshim-preserve-runtime-fdt-and-size.patch',
    '0007-bootshim-runtime-handoff-size-and-cache.patch',
    '0008-sec-onyx-fdt-handoff-guard.patch',
    '0009-onyx-dsc-fdf-unixnu-integration.patch',
    '0010-bootshim-and-handoff-host-tests.patch',
    '0011-onyx-bringup-report-driver.patch',
    '0012-onyx-unixnudxe-direct-start-fallback.patch',
    '0013-onyx-boot-path-host-tests.patch',
    '0014-onyx-device-boot-manager-handoff.patch',
]

# Apply tree per patch. M = Mu-Silicium checkout at the baseline commit (the
# host tests live there too, under Tests/); U = the external UniXNU checkout
# mounted as Mu-Silicium/UniXNUPkg. Only 0012 targets U.
TARGETS = {
    '0001-bootshim-preserve-runtime-fdt-and-size.patch': 'M',
    '0007-bootshim-runtime-handoff-size-and-cache.patch': 'M',
    '0008-sec-onyx-fdt-handoff-guard.patch': 'M',
    '0009-onyx-dsc-fdf-unixnu-integration.patch': 'M',
    '0010-bootshim-and-handoff-host-tests.patch': 'M',
    '0011-onyx-bringup-report-driver.patch': 'M',
    '0012-onyx-unixnudxe-direct-start-fallback.patch': 'U',
    '0013-onyx-boot-path-host-tests.patch': 'M',
    '0014-onyx-device-boot-manager-handoff.patch': 'M',
}

# The port's Mu checkout, resolved the way tests/test_accept_firmware.py does
# (ONYX_UEFI, else a sibling checkout). It is optional here: a checkout that is
# not present is skipped, a Mu checkout missing a mount is a failure.
MU = Path(os.environ.get('ONYX_UEFI', DEVICE.parent / 'Mu-Silicium')).resolve()
UNIXNU_DEFAULT = Path(os.environ.get('ONYX_UNIXNU', DEVICE.parent / 'UniXNU'))
UNIXNU_DRIVER = 'package/UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.c'

# External checkouts the Mu tree consumes through untracked symlinks: name ->
# (path inside the UniXNU checkout, a file that must exist through the mount,
# why a build of this platform needs it). Neither link is in a patch and neither
# is tracked by Mu, so a tree rebuilt from the series has to be given them.
MOUNTS = {
    'UniXNUPkg': (
        UNIXNU_DRIVER.rpartition('/Driver/')[0],
        'Driver/UniXNUDxe/UniXNUDxe.c',
        'patch 0012 rewrites UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.c, and the '
        'DSC/FDF that 0009 lands name UniXNUPkg modules',
    ),
    'DarwinBootPkg': (
        'drivers/DarwinBoot/DarwinBootPkg',
        'Driver/DarwinBoot.inf',
        'the Mu baseline platform already names '
        'DarwinBootPkg/Driver/DarwinBoot.inf in onyx.dsc and onyx.fdf, and the '
        'Mu commit does not carry that module',
    ),
}


def mount_problem(mu=MU, unixnu=UNIXNU_DEFAULT):
    """Why a Mu tree cannot build the series' platform, or None when it can.

    Returns a human-readable sentence instead of letting `git apply` report a
    missing file or `build` report a missing module, because the missing mount
    is the actual problem.
    """
    if not mu.is_dir():
        return None  # nothing to check; the tree is not present here
    problems = []
    for name, (relative, probe, reason) in sorted(MOUNTS.items()):
        mount = mu / name
        if not mount.exists():
            problems.append(
                f'{name} is not mounted at {mount}: {reason}. Link the external '
                f'UniXNU checkout there (`ln -s {unixnu / relative} {mount}`); '
                'without it the port tree is incomplete, not the patch.')
        elif not (mount / probe).is_file():
            problems.append(
                f'{mount} does not resolve to a UniXNU checkout (no {probe}).')
    return ' '.join(problems) if problems else None


# Trees a patch writes to, resolved from its own `diff --git` paths.
def patch_tree(name):
    return 'U' if any(path.startswith('UniXNUPkg/') for path, _, _ in entries(name)) else 'M'


DIFF_GIT = re.compile(
    r'^diff --git a/(?P<path>\S+) b/\S+\n'
    r'(?:(?:new file mode|deleted file mode) \d+\n)?'
    r'(?:index (?P<pre>[0-9a-f]+)\.\.(?P<post>[0-9a-f]+)[^\n]*\n)?',
    re.MULTILINE)


def patch_files():
    return sorted(path.name for path in UEFI.glob('*.patch'))


def patch_text(name):
    return (UEFI / name).read_bytes().decode('utf-8', 'replace')


def entries(name):
    """(path, pre-image hash, post-image hash) for every file a patch touches.

    The hashes are the blob ids git writes on the `index` line; they are what
    makes the stack checkable without the Mu tree.
    """
    found = []
    for match in DIFF_GIT.finditer(patch_text(name)):
        if match.group('pre') is None:
            continue
        found.append((match.group('path'), match.group('pre'), match.group('post')))
    return found


def header(name):
    """Leading '#' comment block, up to the first diff line."""
    lines = []
    for line in patch_text(name).splitlines():
        if line.startswith('diff --git') or line.startswith('--- '):
            break
        lines.append(line)
    return '\n'.join(lines)


class UefiSeriesTests(unittest.TestCase):
    def test_series_list_is_exactly_the_reviewed_one(self):
        self.assertEqual(patch_files(), SERIES)
        self.assertEqual(sorted(TARGETS), SERIES, 'TARGETS must cover every patch')

    def test_each_patch_targets_the_tree_its_paths_belong_to(self):
        for name in patch_files():
            self.assertEqual(patch_tree(name), TARGETS[name],
                             f'{name} writes outside the tree TARGETS claims for it')

    def test_only_the_driver_patch_crosses_into_the_external_tree(self):
        external = [name for name in SERIES if TARGETS[name] == 'U']
        self.assertEqual(external, ['0012-onyx-unixnudxe-direct-start-fallback.patch'])

    def test_unixnupkg_mount_is_present_when_the_mu_tree_is(self):
        problem = mount_problem()
        if problem is not None:
            self.fail(problem)
        if not MU.is_dir():
            self.skipTest(f'no Mu-Silicium checkout at {MU} (set ONYX_UEFI); mount check not applicable')

    def test_numbers_are_unique_and_ascending(self):
        numbers = [int(name[:4]) for name in patch_files()]
        self.assertEqual(numbers, sorted(set(numbers)))

    def test_patches_chain_through_blob_hashes(self):
        """Each patch starts from the content the previous ones produced.

        A file may be patched by more than one patch, but only in order: the
        pre-image blob of the later patch must be the post-image blob of the
        earlier one. Patches that all diff the pristine baseline blob are what
        made this series fail when applied in order.
        """
        produced = {}
        for name in patch_files():
            for path, pre, post in entries(name):
                if pre.strip('0') == '':
                    self.assertNotIn(path, produced, f'{name} re-creates {path}')
                elif path in produced:
                    self.assertTrue(
                        produced[path].startswith(pre) or pre.startswith(produced[path]),
                        f'{name} expects {path} at {pre}, but the series produces '
                        f'{produced[path]} before it: the patches overlap a stale baseline')
                produced[path] = post

    def test_every_patch_documents_scope_and_limits(self):
        for name in patch_files():
            block = header(name)
            self.assertTrue(block.startswith('# '), f'{name} has no header comment block')
            self.assertIn('Scope:', block, name)
            self.assertIn('Limits:', block, name)

    def test_withdrawn_patches_are_documented_where_their_content_landed(self):
        # 0002 bootshim step and DSC/FDF wiring were folded into 0007 and 0009.
        self.assertIn('Fold:', header('0007-bootshim-runtime-handoff-size-and-cache.patch'))
        self.assertIn('Fold:', header('0009-onyx-dsc-fdf-unixnu-integration.patch'))

    def test_sec_handoff_guard_stays_compiled_in(self):
        # Dropping this flag silently removes the SEC FDT guard from the
        # firmware; accept-firmware.py then rejects the FD. Keep it pinned.
        text = patch_text('0009-onyx-dsc-fdf-unixnu-integration.patch')
        self.assertIn('+  *_CLANGPDB_AARCH64_CC_FLAGS = -DONYX_FDT_HANDOFF=1', text)

    def test_boot_path_fallback_patches_are_present(self):
        driver = patch_text('0012-onyx-unixnudxe-direct-start-fallback.patch')
        self.assertIn('UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.c', driver)
        self.assertIn('ONYX-BOOT: ', driver)
        self.assertIn('gEfiEventReadyToBootGuid', driver)
        self.assertIn('gBS->LoadImage', driver)
        tests = patch_text('0013-onyx-boot-path-host-tests.patch')
        self.assertIn('Tests/OnyxBootPath/test_onyx_boot_path.py', tests)

    def test_no_patch_creates_a_mount(self):
        """The links are tree prerequisites, not series content.

        A `diff --git` entry whose path is exactly a mount name would be a patch
        trying to carry a link into somebody else's checkout - it cannot be right
        for any layout but the one it was generated in. Writing *through* a mount
        (`UniXNUPkg/Driver/...`) is expected; creating the mount itself is not.
        """
        for name in patch_files():
            for path, _, _ in entries(name):
                self.assertNotIn(path, MOUNTS, f'{name} creates the {path} mount')

    def test_the_driver_patch_documents_what_it_cannot_be_applied_to(self):
        """`git apply` cannot write through the UniXNUPkg symlink.

        Applying in SERIES order from the Mu tree with the mount linked fails
        with "outside the symlink", so the header has to keep saying where 0012
        lands and that the link is for the build, not for the patch.
        """
        block = header('0012-onyx-unixnudxe-direct-start-fallback.patch')
        self.assertIn('--directory=package', block)
        self.assertIn('outside the symlink', block)

    def test_mount_problem_reports_the_missing_mount_by_name(self):
        # The guard has to be able to fail; a helper that returns None for any
        # input would make every mount assertion vacuous.
        with tempfile.TemporaryDirectory() as empty:
            problem = mount_problem(mu=Path(empty), unixnu=UNIXNU_DEFAULT)
        self.assertIsNotNone(problem)
        for name in MOUNTS:
            self.assertIn(name, problem)


if __name__ == '__main__':
    unittest.main()
