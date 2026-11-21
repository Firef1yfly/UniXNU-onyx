/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Diagnostic snapshot only. Allocates/frees temporary pool buffers, so the
 * observed EFI map includes diagnostic allocation overhead. Does not change
 * MMU attributes, create HOBs, install protocols, or map RAM as conventional.
 * Not yet compiled, integrated, or device-qualified.
 */
#include <Uefi.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/DebugLib.h>
#include <Protocol/EFIRamPartition.h>

#define ONYX_MAP_MAX_BYTES (16 * 1024 * 1024)
#define ONYX_MAP_MAX_PARTITIONS 4096
#define ONYX_MAP_MAX_ATTEMPTS 4

STATIC VOID PrintMap(VOID) {
  EFI_STATUS Status;
  UINTN Bytes = 0, Key = 0, Stride = 0, Capacity = 0, Offset, Attempt;
  UINT32 Version = 0;
  EFI_MEMORY_DESCRIPTOR *Map = NULL, *Entry;

  for (Attempt = 0; Attempt < ONYX_MAP_MAX_ATTEMPTS; ++Attempt) {
    Bytes = Capacity;
    Status = gBS->GetMemoryMap(&Bytes, Map, &Key, &Stride, &Version);
    if (Status == EFI_BUFFER_TOO_SMALL) {
      if (Stride < sizeof(EFI_MEMORY_DESCRIPTOR) ||
          Stride > ONYX_MAP_MAX_BYTES / 2 || Bytes > ONYX_MAP_MAX_BYTES - 2 * Stride) {
        DEBUG((EFI_D_ERROR, "ONYXMAP: EFI invalid capacity bytes=%lu stride=%lu\n", (UINT64)Bytes, (UINT64)Stride));
        break;
      }
      if (Map != NULL) { FreePool(Map); Map = NULL; }
      Capacity = Bytes + 2 * Stride;
      Map = AllocatePool(Capacity);
      if (Map == NULL) {
        DEBUG((EFI_D_ERROR, "ONYXMAP: EFI allocation failed\n"));
        break;
      }
      continue;
    }
    if (EFI_ERROR(Status) || Map == NULL || Stride < sizeof(*Map) ||
        Bytes > Capacity || Bytes == 0 || Bytes % Stride != 0 ||
        Version != EFI_MEMORY_DESCRIPTOR_VERSION) {
      DEBUG((EFI_D_ERROR, "ONYXMAP: EFI invalid snapshot status=%r bytes=%lu stride=%lu version=%u\n", Status, (UINT64)Bytes, (UINT64)Stride, Version));
      break;
    }
    /* Print only after successful bounded snapshot; formatting/logging may
     * subsequently allocate, so this is NOT an ExitBootServices map/key. */
    DEBUG((EFI_D_ERROR, "ONYXMAP: EFI begin bytes=%lu stride=%lu version=%u\n", (UINT64)Bytes, (UINT64)Stride, Version));
    for (Offset = 0; Offset < Bytes; Offset += Stride) {
      Entry = (EFI_MEMORY_DESCRIPTOR *)((UINT8 *)Map + Offset);
      if (Entry->NumberOfPages == 0 || Entry->NumberOfPages > MAX_UINT64 / EFI_PAGE_SIZE ||
          Entry->PhysicalStart > MAX_UINT64 - Entry->NumberOfPages * EFI_PAGE_SIZE) {
        DEBUG((EFI_D_ERROR, "ONYXMAP: EFI invalid range index=%lu\n", (UINT64)(Offset / Stride)));
        continue;
      }
      DEBUG((EFI_D_ERROR, "ONYXMAP: type=%u base=0x%016lx pages=0x%lx attr=0x%016lx\n", Entry->Type, Entry->PhysicalStart, Entry->NumberOfPages, Entry->Attribute));
    }
    DEBUG((EFI_D_ERROR, "ONYXMAP: EFI end\n"));
    break;
  }
  if (Attempt == ONYX_MAP_MAX_ATTEMPTS) DEBUG((EFI_D_ERROR, "ONYXMAP: EFI retry limit\n"));
  if (Map != NULL) FreePool(Map);
}

STATIC VOID PrintPartitions(VOID) {
  EFI_RAMPARTITION_PROTOCOL *Protocol = NULL;
  EFI_STATUS Status;
  RamPartitionEntry *Entries = NULL;
  UINT32 Count = 0, Capacity = 0, Index, Attempt;

  Status = gBS->LocateProtocol(&gEfiRamPartitionProtocolGuid, NULL, (VOID **)&Protocol);
  if (EFI_ERROR(Status) || Protocol == NULL || Protocol->GetRamPartitions == NULL) {
    DEBUG((EFI_D_ERROR, "ONYXMAP: RAM protocol unavailable status=%r\n", Status));
    return;
  }
  /* UINT32 counts are never narrowed to UINT8. Limit all protocol requests. */
  for (Attempt = 0; Attempt < ONYX_MAP_MAX_ATTEMPTS; ++Attempt) {
    Count = Capacity;
    Status = Protocol->GetRamPartitions(Protocol, Entries, &Count);
    if (Status == EFI_BUFFER_TOO_SMALL || (!EFI_ERROR(Status) && Entries == NULL && Count > 0)) {
      if (Count == 0 || Count > ONYX_MAP_MAX_PARTITIONS) {
        DEBUG((EFI_D_ERROR, "ONYXMAP: RAM invalid count=%u\n", Count));
        break;
      }
      if (Entries != NULL) { FreePool(Entries); Entries = NULL; }
      Capacity = Count;
      Entries = AllocatePool(sizeof(*Entries) * Capacity);
      if (Entries == NULL) { DEBUG((EFI_D_ERROR, "ONYXMAP: RAM allocation failed\n")); break; }
      continue;
    }
    if (EFI_ERROR(Status) || Count > Capacity || (Count != 0 && Entries == NULL)) {
      DEBUG((EFI_D_ERROR, "ONYXMAP: RAM invalid result status=%r count=%u capacity=%u\n", Status, Count, Capacity));
      break;
    }
    DEBUG((EFI_D_ERROR, "ONYXMAP: RAM begin count=%u\n", Count));
    for (Index = 0; Index < Count; ++Index) {
      if (Entries[Index].AvailableLength == 0 ||
          Entries[Index].Base > MAX_UINT64 - Entries[Index].AvailableLength) {
        DEBUG((EFI_D_ERROR, "ONYXMAP: RAM invalid range index=%u\n", Index));
        continue;
      }
      DEBUG((EFI_D_ERROR, "ONYXMAP: ram[%u] base=0x%016lx available=0x%016lx\n", Index, Entries[Index].Base, Entries[Index].AvailableLength));
    }
    DEBUG((EFI_D_ERROR, "ONYXMAP: RAM end\n"));
    break;
  }
  if (Attempt == ONYX_MAP_MAX_ATTEMPTS) DEBUG((EFI_D_ERROR, "ONYXMAP: RAM retry limit\n"));
  if (Entries != NULL) FreePool(Entries);
}

EFI_STATUS EFIAPI OnyxMapDxeEntry(IN EFI_HANDLE ImageHandle, IN EFI_SYSTEM_TABLE *SystemTable) {
  (VOID)ImageHandle;
  (VOID)SystemTable;
  DEBUG((EFI_D_ERROR, "ONYXMAP: diagnostic snapshot, not a handoff memory contract\n"));
  PrintMap();
  PrintPartitions();
  return EFI_SUCCESS;
}
