import Foundation
import Vision
import AppKit
import CoreGraphics

// Local JSON-lines worker. No network, registration, or database access.
struct Input: Decodable {
    let image: String
    let annotated: String?
    let roi: [Double]?
    let restrictROI: Bool?
}
struct Detection: Codable {
    let text: String
    let confidence: Float
    let bbox: [Double] // pixels, top-left origin: x, y, width, height
    let region: String
}
struct Output: Encodable {
    let width: Int
    let height: Int
    let processing_ms: Double
    let detections: [Detection]
}

func recognize(_ input: Input) throws -> Output {
    let start = ProcessInfo.processInfo.systemUptime
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: input.image) as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw NSError(domain: "OCR", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot read image"])
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    let roi = input.roi ?? [0, 0.115, 1, 0.24]
    if input.restrictROI == true {
        request.regionOfInterest = CGRect(x: roi[0], y: 1 - roi[3], width: roi[2] - roi[0], height: roi[3] - roi[1])
    }
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    let w = Double(image.width), h = Double(image.height)
    let detections = (request.results ?? []).compactMap { observation -> Detection? in
        guard let text = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        // Vision's text boxes are relative to the request ROI, not the full image.
        let area = input.restrictROI == true ? roi : [0, 0, 1, 1]
        let areaW = area[2] - area[0], areaH = area[3] - area[1]
        let box = [(area[0] + b.minX * areaW) * w,
                   (area[1] + (1 - b.maxY) * areaH) * h,
                   b.width * areaW * w, b.height * areaH * h]
        let cx = (box[0] + box[2] / 2) / w, cy = (box[1] + box[3] / 2) / h
        let inROI = cx >= roi[0] && cx <= roi[2] && cy >= roi[1] && cy <= roi[3]
        return Detection(text: text.string, confidence: text.confidence, bbox: box,
                         region: inROI ? "danmaku_candidate" : "outside_danmaku_region")
    }
    if let destination = input.annotated {
        guard !FileManager.default.fileExists(atPath: destination) else {
            throw NSError(domain: "OCR", code: 2, userInfo: [NSLocalizedDescriptionKey: "Annotation file already exists"])
        }
        let canvas = NSImage(size: NSSize(width: w, height: h))
        canvas.lockFocus()
        NSGraphicsContext.current!.cgContext.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        for (index, item) in detections.enumerated() {
            let b = item.bbox
            let color = item.region == "danmaku_candidate" ? NSColor.systemGreen : NSColor.systemOrange
            color.setStroke()
            let rect = NSRect(x: b[0], y: h - b[1] - b[3], width: b[2], height: b[3])
            let path = NSBezierPath(rect: rect); path.lineWidth = 1.5; path.stroke()
            let label = "\(index + 1) \(String(format: "%.2f", item.confidence))"
            (label as NSString).draw(at: NSPoint(x: b[0], y: min(h - 12, rect.maxY)),
                withAttributes: [.font: NSFont.systemFont(ofSize: 10), .foregroundColor: color,
                                 .backgroundColor: NSColor.black.withAlphaComponent(0.8)])
        }
        canvas.unlockFocus()
        guard let tiff = canvas.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            throw NSError(domain: "OCR", code: 3)
        }
        try png.write(to: URL(fileURLWithPath: destination), options: .withoutOverwriting)
    }
    return Output(width: image.width, height: image.height,
                  processing_ms: (ProcessInfo.processInfo.systemUptime - start) * 1000,
                  detections: detections)
}

while let line = readLine() {
    do {
        let input = try JSONDecoder().decode(Input.self, from: Data(line.utf8))
        let result = try recognize(input)
        print(String(data: try JSONEncoder().encode(result), encoding: .utf8)!)
    } catch {
        let result = ["error": error.localizedDescription]
        print(String(data: try! JSONSerialization.data(withJSONObject: result), encoding: .utf8)!)
    }
    fflush(stdout)
}
