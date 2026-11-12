import Foundation
import CoreGraphics
import ImageIO
import CoreText

// Offline image crops only. Input is a manifest of existing frames, never screen capture.
let manifestURL = URL(fileURLWithPath: CommandLine.arguments[1])
let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as! [String: Any]
let rows = manifest["rows"] as! [[String: Any]]
let root = URL(fileURLWithPath: manifest["source_run"] as! String)
let width = 1040, rowHeight = 154
let context = CGContext(data: nil, width: width, height: rows.count * rowHeight, bitsPerComponent: 8,
                        bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
context.setFillColor(CGColor(gray: 0.12, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: width, height: rows.count * rowHeight))
func label(_ text: String, _ x: Double, _ y: Double, _ size: Double = 14) {
    let attributes: [NSAttributedString.Key:Any] = [NSAttributedString.Key(kCTFontAttributeName as String): CTFontCreateWithName("PingFangSC-Regular" as CFString, size, nil), NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 1, alpha: 1)]
    context.textPosition = CGPoint(x:x,y:y)
    CTLineDraw(CTLineCreateWithAttributedString(NSAttributedString(string:text,attributes:attributes)),context)
}
for (i, row) in rows.enumerated() {
    let y = Double((rows.count-i-1)*rowHeight)
    label(row["title"] as! String, 10, y+135, 16)
    for (column, name) in ["original", "corrected"].enumerated() {
        let item = row[name] as! [String:Any]
        let x = Double(column * 520 + 10)
        label("\(name): \(item["text"]!)", x, y+112)
        label("Vision: \(item["confidence"]!) · \(item["screenshot"]!)", x, y+92, 11)
        let source = CGImageSourceCreateWithURL(root.appendingPathComponent(item["screenshot"] as! String) as CFURL, nil)!
        let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
        let b = item["bbox"] as! [Double]
        let rect = CGRect(x:max(0,b[0]-8),y:max(0,b[1]-6),width:min(Double(image.width)-max(0,b[0]-8),b[2]+36),height:b[3]+12).integral
        let crop = image.cropping(to:rect)!
        let scale = min(2, min(500/Double(crop.width), 78/Double(crop.height)))
        context.draw(crop,in:CGRect(x:x,y:y+5,width:Double(crop.width)*scale,height:Double(crop.height)*scale))
    }
}
let output = URL(fileURLWithPath: CommandLine.arguments[2])
guard !FileManager.default.fileExists(atPath:output.path) else { fatalError("Refusing overwrite") }
let destination = CGImageDestinationCreateWithURL(output as CFURL,"public.png" as CFString,1,nil)!
CGImageDestinationAddImage(destination,context.makeImage()!,nil)
guard CGImageDestinationFinalize(destination) else { fatalError("PNG write failed") }
print(output.path)
