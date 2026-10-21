// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "MixnavutsKit",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "MixnavutsKit", targets: ["MixnavutsKit"]),
    ],
    targets: [
        .target(name: "MixnavutsKit"),
        .testTarget(name: "MixnavutsKitTests", dependencies: ["MixnavutsKit"]),
    ]
)
