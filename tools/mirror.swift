// Controlador para la ventana "iPhone Mirroring" (Duplicación del iPhone).
// Uso:
//   swift mirror.swift info                      -> JSON con bounds de la ventana
//   swift mirror.swift shot <out.png>            -> captura solo la ventana
//   swift mirror.swift diff <a.png> <b.png>    -> fracción de pixeles distintos
//   swift mirror.swift ocr <img.png>             -> JSON [{text, conf, x, y, w, h}] (coords normalizadas 0-1, origen arriba-izq)
//   swift mirror.swift tap <nx> <ny>             -> toque en coords normalizadas de la ventana
//   swift mirror.swift scroll <nx> <ny> <pixeles>  -> scroll con rueda (negativo = bajar)
//   swift mirror.swift swipe <nx1> <ny1> <nx2> <ny2>
//   swift mirror.swift type "<texto>"
//   swift mirror.swift key <home|back|switcher|return|delete|escape>
import AppKit
import CoreGraphics
import Foundation
import Vision

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

func mirrorWindow() -> (id: CGWindowID, bounds: CGRect) {
    let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    for w in list {
        let owner = w[kCGWindowOwnerName as String] as? String ?? ""
        let layer = w[kCGWindowLayer as String] as? Int ?? -1
        guard layer == 0, owner.contains("iPhone") else { continue }
        let b = w[kCGWindowBounds as String] as! [String: CGFloat]
        let rect = CGRect(x: b["X"]!, y: b["Y"]!, width: b["Width"]!, height: b["Height"]!)
        if rect.width < 150 { continue }
        return (w[kCGWindowNumber as String] as! CGWindowID, rect)
    }
    fail("No se encontró la ventana de iPhone Mirroring (¿está abierta y visible?)")
}

func activate() {
    if let app = NSWorkspace.shared.runningApplications.first(where: { ($0.localizedName ?? "").contains("iPhone") && $0.activationPolicy == .regular }) {
        app.activate()
        usleep(150_000)
    }
}

func point(_ nx: Double, _ ny: Double) -> CGPoint {
    let b = mirrorWindow().bounds
    return CGPoint(x: b.minX + b.width * nx, y: b.minY + b.height * ny)
}

func mouse(_ type: CGEventType, _ p: CGPoint) {
    CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: p, mouseButton: .left)!.post(tap: .cghidEventTap)
}

func shot(_ out: String) {
    let w = mirrorWindow()
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
    task.arguments = ["-x", "-o", "-l", String(w.id), out]
    try! task.run(); task.waitUntilExit()
    if task.terminationStatus != 0 { fail("screencapture falló") }
}

func ocr(_ path: String) {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { fail("No pude leer \(path)") }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["es-ES", "en-US"]
    req.usesLanguageCorrection = false
    try! VNImageRequestHandler(cgImage: cg).perform([req])
    var out: [[String: Any]] = []
    for o in req.results ?? [] {
        guard let c = o.topCandidates(1).first else { continue }
        let bb = o.boundingBox
        out.append(["text": c.string, "conf": Double(c.confidence),
                    "x": bb.minX, "y": 1 - bb.maxY, "w": bb.width, "h": bb.height])
    }
    let data = try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted])
    print(String(data: data, encoding: .utf8)!)
}

func keyPress(_ code: CGKeyCode, flags: CGEventFlags = []) {
    let d = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true)!; d.flags = flags; d.post(tap: .cghidEventTap)
    let u = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false)!; u.flags = flags; u.post(tap: .cghidEventTap)
    usleep(40_000)
}

let args = CommandLine.arguments
guard args.count >= 2 else { fail("falta comando") }
switch args[1] {
case "info":
    let w = mirrorWindow()
    print("{\"id\":\(w.id),\"x\":\(w.bounds.minX),\"y\":\(w.bounds.minY),\"w\":\(w.bounds.width),\"h\":\(w.bounds.height)}")
case "shot":
    shot(args[2])
case "ocr":
    ocr(args[2])
case "diff":
    // fracción de pixeles distintos (ignora barra de estado) entre dos capturas
    func gray(_ path: String) -> [UInt8] {
        guard let img = NSImage(contentsOfFile: path),
              let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { fail("No pude leer \(path)") }
        let top = Int(Double(cg.height) * 0.12)
        let crop = cg.cropping(to: CGRect(x: 0, y: top, width: cg.width, height: cg.height - top))!
        var px = [UInt8](repeating: 0, count: 160 * 320)
        let ctx = CGContext(data: &px, width: 160, height: 320, bitsPerComponent: 8, bytesPerRow: 160,
                            space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
        ctx.draw(crop, in: CGRect(x: 0, y: 0, width: 160, height: 320))
        return px
    }
    let a = gray(args[2]), b = gray(args[3])
    var n = 0
    for i in 0..<a.count where abs(Int(a[i]) - Int(b[i])) > 24 { n += 1 }
    print(String(format: "%.5f", Double(n) / Double(a.count)))
case "tap":
    activate()
    let p = point(Double(args[2])!, Double(args[3])!)
    mouse(.mouseMoved, p); usleep(50_000)
    mouse(.leftMouseDown, p); usleep(60_000); mouse(.leftMouseUp, p)
case "swipe":
    activate()
    let a = point(Double(args[2])!, Double(args[3])!), b = point(Double(args[4])!, Double(args[5])!)
    mouse(.leftMouseDown, a)
    for i in 1...20 {
        let t = CGFloat(i) / 20
        mouse(.leftMouseDragged, CGPoint(x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t)); usleep(15_000)
    }
    mouse(.leftMouseUp, b)
case "scroll":
    // scroll con rueda (pixeles; negativo = bajar contenido) sobre un punto de la ventana
    activate()
    let p = point(Double(args[2])!, Double(args[3])!)
    mouse(.mouseMoved, p); usleep(50_000)
    let total = Int32(args[4])!, steps: Int32 = 12
    for _ in 0..<steps {
        CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: total / steps, wheel2: 0, wheel3: 0)!.post(tap: .cghidEventTap)
        usleep(16_000)
    }
case "type":
    activate()
    for ch in args[2].utf16 {
        let d = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true)!
        var c = ch; d.keyboardSetUnicodeString(stringLength: 1, unicodeString: &c); d.post(tap: .cghidEventTap)
        let u = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false)!
        u.keyboardSetUnicodeString(stringLength: 1, unicodeString: &c); u.post(tap: .cghidEventTap)
        usleep(30_000)
    }
case "key":
    activate()
    switch args[2] {
    case "home": keyPress(18, flags: .maskCommand)         // Cmd+1 en iPhone Mirroring = Inicio
    case "switcher": keyPress(19, flags: .maskCommand)     // Cmd+2 = selector de apps
    case "return": keyPress(36)
    case "delete": keyPress(51)
    case "escape": keyPress(53)
    default: fail("tecla desconocida")
    }
default:
    fail("comando desconocido")
}
