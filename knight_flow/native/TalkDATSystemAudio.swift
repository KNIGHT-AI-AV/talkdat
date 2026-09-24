// Audio-only ScreenCaptureKit helper. No screen output or image is requested.
import Foundation
import AVFoundation
import ScreenCaptureKit
import CoreGraphics
import Darwin

enum CaptureFailure: Error { case format, buffer }

func pcm16(_ buffer: AVAudioPCMBuffer) throws -> Data {
    guard buffer.format.sampleRate == 48000, buffer.format.channelCount == 2,
          buffer.frameLength <= 16384 else { throw CaptureFailure.format }
    let count = Int(buffer.frameLength)
    let interleaved = buffer.format.isInterleaved
    var output = [Int16](repeating: 0, count: count * 2)
    if buffer.format.commonFormat == .pcmFormatFloat32, let data = buffer.floatChannelData {
        for frame in 0..<count {
            for channel in 0..<2 {
                let value = data[interleaved ? 0 : channel][frame * buffer.stride + (interleaved ? channel : 0)]
                guard value.isFinite else { throw CaptureFailure.buffer }
                output[frame * 2 + channel] = Int16(max(-32768, min(32767, (Double(value) * 32768).rounded())))
            }
        }
    } else if buffer.format.commonFormat == .pcmFormatInt16, let data = buffer.int16ChannelData {
        for frame in 0..<count {
            for channel in 0..<2 { output[frame * 2 + channel] = data[interleaved ? 0 : channel][frame * buffer.stride + (interleaved ? channel : 0)] }
        }
    } else { throw CaptureFailure.format }
    return output.withUnsafeBytes { Data($0) }
}

final class PacketWriter: @unchecked Sendable {
    let queue = DispatchQueue(label: "TalkDAT.SystemAudio.Output")
    let slots = DispatchSemaphore(value: 8)
    private let failureLock = NSLock()
    private var failed = false
    func send(_ type: UInt8, _ data: Data = Data()) {
        var size = UInt32(data.count + 1).littleEndian
        var packet = withUnsafeBytes(of: &size) { Data($0) }
        packet.append(type); packet.append(data)
        packet.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                let written = Darwin.write(STDOUT_FILENO, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                if written < 0 && errno == EINTR { continue }
                guard written > 0 else { exit(4) }
                offset += written
            }
        }
    }
    func audio(_ data: Data) -> Bool {
        guard slots.wait(timeout: .now()) == .success else { return false }
        queue.async { self.send(2, data); self.slots.signal() }
        return true
    }
    func fail(_ code: String) {
        failureLock.lock()
        if failed { failureLock.unlock(); return }
        failed = true
        failureLock.unlock()
        queue.async { self.send(3, Data(code.utf8)); exit(3) }
    }
}

@available(macOS 13.0, *)
final class AudioCapture: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    let writer = PacketWriter()
    let audioQueue = DispatchQueue(label: "TalkDAT.SystemAudio.Capture")
    @MainActor var stream: SCStream?
    @MainActor func start() async throws {
        guard CGPreflightScreenCaptureAccess() else {
            writer.fail("permission"); return
        }
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
        guard let display = content.displays.first else { writer.fail("display"); return }
        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.sampleRate = 48000
        config.channelCount = 2
        config.excludesCurrentProcessAudio = true
        config.width = 2; config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.queueDepth = 3
        config.showsCursor = false
        let capture = SCStream(filter: filter, configuration: config, delegate: self)
        try capture.addStreamOutput(self, type: .audio, sampleHandlerQueue: audioQueue)
        stream = capture
        try await capture.startCapture()
        writer.queue.async { self.writer.send(1) }
    }
    @MainActor func stop() async {
        do { try await stream?.stopCapture() }
        catch { writer.fail("stop"); return }
        audioQueue.async {
            self.writer.queue.async { self.writer.send(4); exit(0) }
        }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { writer.fail("device") }
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        guard sampleBuffer.isValid, CMSampleBufferDataIsReady(sampleBuffer),
              let description = CMSampleBufferGetFormatDescription(sampleBuffer) else { writer.fail("buffer"); return }
        let format = AVAudioFormat(cmAudioFormatDescription: description)
        let frames = CMSampleBufferGetNumSamples(sampleBuffer)
        guard frames > 0 else { return }
        guard frames <= 16384, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)) else {
            writer.fail("format"); return
        }
        buffer.frameLength = AVAudioFrameCount(frames)
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(sampleBuffer, at: 0, frameCount: Int32(frames), into: buffer.mutableAudioBufferList) == noErr else {
            writer.fail("buffer"); return
        }
        do { if !writer.audio(try pcm16(buffer)) { writer.fail("overflow") } }
        catch { writer.fail("format") }
    }
}

func selfTest() throws {
    var checks = 0
    for interleaved in [false, true] {
        for common in [AVAudioCommonFormat.pcmFormatFloat32, .pcmFormatInt16] {
            let format = AVAudioFormat(commonFormat: common, sampleRate: 48000, channels: 2, interleaved: interleaved)!
            let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 3)!
            buffer.frameLength = 3
            for frame in 0..<3 {
                if common == .pcmFormatFloat32 {
                    buffer.floatChannelData![0][frame * buffer.stride] = 0.5
                    buffer.floatChannelData![interleaved ? 0 : 1][frame * buffer.stride + (interleaved ? 1 : 0)] = -0.5
                } else {
                    buffer.int16ChannelData![0][frame * buffer.stride] = 16384
                    buffer.int16ChannelData![interleaved ? 0 : 1][frame * buffer.stride + (interleaved ? 1 : 0)] = -16384
                }
            }
            let raw = try pcm16(buffer)
            let expected: [Int16] = [16384,-16384,16384,-16384,16384,-16384]
            precondition(raw == expected.withUnsafeBytes { Data($0) }); checks += 1
        }
    }
    let format = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 2)!
    let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 2)!
    buffer.frameLength = 2
    buffer.floatChannelData![0][0] = 2; buffer.floatChannelData![0][1] = -2
    buffer.floatChannelData![1][0] = 1; buffer.floatChannelData![1][1] = -1
    let expected: [Int16] = [32767,32767,-32768,-32768]
    let clipped = try pcm16(buffer)
    precondition(clipped == expected.withUnsafeBytes { Data($0) }); checks += 1
    buffer.floatChannelData![0][0] = .nan
    do { _ = try pcm16(buffer); fatalError("Non-finite PCM was accepted") } catch { checks += 1 }
    print("PASS \(checks) native PCM conversion checks; no capture or permission request")
}

signal(SIGPIPE, SIG_IGN)
if CommandLine.arguments.contains("--protocol-test") {
    let writer = PacketWriter()
    writer.send(1)
    let samples: [Int16] = [16384, -16384, 1000, -1000]
    writer.send(2, samples.withUnsafeBytes { Data($0) })
    var byte: UInt8 = 0
    _ = Darwin.read(STDIN_FILENO, &byte, 1)
    writer.send(4)
    exit(0)
}
if CommandLine.arguments.contains("--self-test") {
    do { try selfTest(); exit(0) } catch { fputs("PCM self-test failed\n", stderr); exit(1) }
}
if CommandLine.arguments.contains("--permission-status") {
    print(CGPreflightScreenCaptureAccess() ? "granted" : "not-granted"); exit(0)
}
if #available(macOS 13.0, *) {
    let capture = AudioCapture()
    Task {
        do { try await capture.start() }
        catch { capture.writer.fail("start") }
    }
    DispatchQueue.global().async {
        var byte: UInt8 = 0
        _ = Darwin.read(STDIN_FILENO, &byte, 1)
        Task { await capture.stop() }
    }
    dispatchMain()
} else {
    PacketWriter().send(3, Data("version".utf8)); exit(2)
}
