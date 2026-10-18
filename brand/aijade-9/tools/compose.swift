import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

// compose <portrait.png> <out.png> <size> <inset 0..1>: the portrait (with alpha) over a soft blue gradient,
// inset so that maskable icons keep the face inside the safe zone.
let args = CommandLine.arguments
let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: args[1]) as CFURL, nil)!
let portrait = CGImageSourceCreateImageAtIndex(src, 0, nil)!
let size = Int(args[3])!
let inset = Double(args[4])!
let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
let colors = [CGColor(red: 0.70, green: 0.82, blue: 0.96, alpha: 1), CGColor(red: 0.90, green: 0.94, blue: 1.0, alpha: 1)] as CFArray
let gradient = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB)!, colors: colors, locations: [0, 1])!
ctx.drawLinearGradient(gradient, start: CGPoint(x: 0, y: 0), end: CGPoint(x: 0, y: size), options: [])
ctx.interpolationQuality = .high
let pad = Double(size) * inset
let side = Double(size) - 2 * pad
// anchor the portrait to the bottom edge so the shoulders run off the frame
ctx.draw(portrait, in: CGRect(x: pad, y: 0, width: side, height: side + pad))
let out = CGImageDestinationCreateWithURL(URL(fileURLWithPath: args[2]) as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(out, ctx.makeImage()!, nil)
CGImageDestinationFinalize(out)
