/** Milesight AM103 / AM103L payload codec for ChirpStack v4. */
function decodeUplink(input) {
    return { data: decodeMilesight(input.bytes) };
}

function decodeMilesight(bytes) {
    var decoded = {};
    for (var i = 0; i + 1 < bytes.length;) {
        var channel = bytes[i++];
        var type = bytes[i++];
        if (channel === 0xff && type === 0x01 && i + 1 <= bytes.length) {
            i += 1; // protocol version
        } else if (channel === 0xff && (type === 0x09 || type === 0x0a || type === 0xff || type === 0x18) && i + 2 <= bytes.length) {
            i += 2; // hardware, firmware, or TSL version
        } else if (channel === 0xff && type === 0x16 && i + 8 <= bytes.length) {
            i += 8; // serial number
        } else if (channel === 0xff && (type === 0x0f || type === 0xfe || type === 0x0b) && i + 1 <= bytes.length) {
            i += 1; // class, reset event, or device status
        } else if (channel === 0x01 && type === 0x75 && i + 1 <= bytes.length) {
            decoded.battery = bytes[i++];
        } else if (channel === 0x03 && type === 0x67 && i + 2 <= bytes.length) {
            decoded.temperature = readInt16LE(bytes, i) / 10;
            i += 2;
        } else if (channel === 0x04 && type === 0x68 && i + 1 <= bytes.length) {
            decoded.humidity = bytes[i++] / 2;
        } else if (channel === 0x07 && type === 0x7d && i + 2 <= bytes.length) {
            decoded.co2 = readUInt16LE(bytes, i);
            i += 2;
        } else if (channel === 0x20 && type === 0xce && i + 9 <= bytes.length) {
            decoded.history = decoded.history || [];
            decoded.history.push({
                timestamp: readUInt32LE(bytes, i),
                temperature: readInt16LE(bytes, i + 4) / 10,
                humidity: bytes[i + 6] / 2,
                co2: readUInt16LE(bytes, i + 7)
            });
            i += 9;
        } else {
            break;
        }
    }
    return decoded;
}

function readUInt16LE(bytes, offset) {
    return bytes[offset] | (bytes[offset + 1] << 8);
}

function readInt16LE(bytes, offset) {
    var value = readUInt16LE(bytes, offset);
    return value > 0x7fff ? value - 0x10000 : value;
}

function readUInt32LE(bytes, offset) {
    return (bytes[offset] + bytes[offset + 1] * 0x100 + bytes[offset + 2] * 0x10000 + bytes[offset + 3] * 0x1000000) >>> 0;
}

function encodeDownlink(input) {
    return { bytes: [] };
}
