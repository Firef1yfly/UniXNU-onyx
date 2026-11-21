# QR logger integration status — round 35

UniXNU already contains the QR menu exporter:

```text
package/UniXNUPkg/Driver/AdvancedLogDxe/AdvancedLogDxe.inf
```

Its dependencies are `AdvLoggerPkg`, `MsGraphicsPkg`, `AdvancedLoggerAccessLib` and `QrEncoderLib`; it waits for `gAdvancedLoggerProtocolGuid` and publishes the UniXNU Tools menu plugin. The official integration procedure is documented in `unixnu/docs/porting/log-capture.md:14-78`.

The current onyx DSC/FDF does **not** include `AdvancedLogDxe`, and current Mu-Silicium search did not find a QR encoder/AdvancedLogger wiring in the active onyx package. Therefore a black screen cannot be diagnosed with QR from the existing FD. Adding only AdvancedLogDxe is insufficient: the Mu revision must provide an AdvancedLogger producer, buffer configuration and QrEncoderLib mapping; `[payload] tools = true` must also add the Tools entry.

Next firmware diagnostic build should add the exporter plus all matching Mu logger libraries and a safe logger buffer reservation, then verify the FFS/build report. Do not repeat the previous map diagnostic image until Tools → Advanced Logger is actually present and a camera/OneSend capture path is ready.
