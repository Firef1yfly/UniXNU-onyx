/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * onyx diagnostic candidate, using Mu-Silicium's existing platform BDS hook.
 * Retains Qualcomm's Mass Storage option and explicitly supplies UniXNU as an
 * active BOOT-category FV application. No new boot manager or direct StartImage.
 */
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PcdLib.h>
#include <Library/PlatformBootOptionsLib.h>

VOID
GetPlatformBootOptions (
  OUT EFI_PLATFORM_BOOT_OPTION **BootOption,
  OUT UINT8 *BootOptionCount
  )
{
  EFI_PLATFORM_BOOT_OPTION *Options;
  EFI_GUID *UniXnuGuid;
  EFI_GUID *MassStorageGuid;

  if ((BootOption == NULL) || (BootOptionCount == NULL)) {
    return;
  }
  *BootOption = NULL;
  *BootOptionCount = 0;

  Options = AllocateZeroPool (2 * sizeof (*Options));
  if (Options == NULL) {
    DEBUG ((DEBUG_ERROR, "ONYXBDS: platform option allocation failed\n"));
    return;
  }

  /* Resolve both PCDs before publishing anything to the caller. */
  UniXnuGuid = (EFI_GUID *)FixedPcdGetPtr (PcdUniXNUApplicationFile);
  MassStorageGuid = (EFI_GUID *)FixedPcdGetPtr (PcdMassStorageFile);
  if ((UniXnuGuid == NULL) || (MassStorageGuid == NULL)) {
    FreePool (Options);
    DEBUG ((DEBUG_ERROR, "ONYXBDS: required application PCD missing\n"));
    return;
  }

  Options[0].AppName = L"UniXNU";
  Options[0].AppGuid = UniXnuGuid;
  Options[0].LoadAttribute = LOAD_OPTION_ACTIVE;

  Options[1].AppName = L"Mass Storage";
  Options[1].AppGuid = MassStorageGuid;
  Options[1].LoadAttribute = LOAD_OPTION_HIDDEN;

  *BootOption = Options;
  *BootOptionCount = 2;
  DEBUG ((DEBUG_INFO, "ONYXBDS: supplying active UniXNU FV app %g and hidden Mass Storage\n", Options[0].AppGuid));
}
