using System.Buffers.Binary;
using System.IO.Compression;
using System.Text;

namespace Aijade.Integrations.Minecraft;

// The reader and writer methods are named after the protocol's own data types (String, Int, Long …) so that packet code
// reads like the protocol tables; the writer's MemoryStream holds no unmanaged resource.
#pragma warning disable CA1720, CA1001

// Minecraft: Java Edition protocol primitives, written from the protocol documentation (minecraft.wiki, "Java Edition
// protocol/Packets", Java Edition 26.3, protocol 777): VarInt/VarLong, strings, packet framing with optional zlib
// compression, and a reader for network NBT text components (the chat format since 1.20.3), reduced to plain text.

public sealed class McWriter
{
    private readonly MemoryStream buffer = new();

    public byte[] ToArray() => buffer.ToArray();

    public McWriter VarInt(int value)
    {
        var v = (uint)value;
        while (true)
        {
            if ((v & ~0x7Fu) == 0)
            {
                buffer.WriteByte((byte)v);
                return this;
            }
            buffer.WriteByte((byte)((v & 0x7F) | 0x80));
            v >>= 7;
        }
    }

    public McWriter String(string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        VarInt(bytes.Length);
        buffer.Write(bytes);
        return this;
    }

    public McWriter UShort(ushort value)
    {
        Span<byte> b = stackalloc byte[2];
        BinaryPrimitives.WriteUInt16BigEndian(b, value);
        buffer.Write(b);
        return this;
    }

    public McWriter Short(short value)
    {
        Span<byte> b = stackalloc byte[2];
        BinaryPrimitives.WriteInt16BigEndian(b, value);
        buffer.Write(b);
        return this;
    }

    public McWriter Int(int value)
    {
        Span<byte> b = stackalloc byte[4];
        BinaryPrimitives.WriteInt32BigEndian(b, value);
        buffer.Write(b);
        return this;
    }

    public McWriter Long(long value)
    {
        Span<byte> b = stackalloc byte[8];
        BinaryPrimitives.WriteInt64BigEndian(b, value);
        buffer.Write(b);
        return this;
    }

    public McWriter Double(double value) => Long(BitConverter.DoubleToInt64Bits(value));

    public McWriter Float(float value) => Int(BitConverter.SingleToInt32Bits(value));

    public McWriter Bool(bool value)
    {
        buffer.WriteByte(value ? (byte)1 : (byte)0);
        return this;
    }

    public McWriter Byte(byte value)
    {
        buffer.WriteByte(value);
        return this;
    }

    public McWriter Bytes(ReadOnlySpan<byte> value)
    {
        buffer.Write(value);
        return this;
    }

    public McWriter Uuid(Guid value)
    {
        Span<byte> b = stackalloc byte[16];
        value.TryWriteBytes(b, bigEndian: true, out _);
        buffer.Write(b);
        return this;
    }
}

public sealed class McReader(byte[] data)
{
    private int pos;

    public bool AtEnd => pos >= data.Length;

    /// <summary>The whole packet body (for diagnostics).</summary>
    public byte[] Payload => data;

    public int Remaining => data.Length - pos;

    /// <summary>A second reader over the same data, starting where this one is now.</summary>
    public McReader Fork() => new(data) { pos = pos };

    public byte Byte() => pos < data.Length ? data[pos++] : throw new EndOfStreamException("packet ended early");

    public ReadOnlySpan<byte> Take(int n)
    {
        if (n < 0 || pos + n > data.Length)
            throw new EndOfStreamException("packet ended early");
        var span = data.AsSpan(pos, n);
        pos += n;
        return span;
    }

    public int VarInt()
    {
        var result = 0;
        for (var shift = 0; shift < 35; shift += 7)
        {
            var b = Byte();
            result |= (b & 0x7F) << shift;
            if ((b & 0x80) == 0)
                return result;
        }
        throw new InvalidDataException("VarInt too long");
    }

    public long VarLong()
    {
        var result = 0L;
        for (var shift = 0; shift < 70; shift += 7)
        {
            var b = Byte();
            result |= (long)(b & 0x7F) << shift;
            if ((b & 0x80) == 0)
                return result;
        }
        throw new InvalidDataException("VarLong too long");
    }

    public string String() => Encoding.UTF8.GetString(Take(VarInt()));

    public bool Bool() => Byte() != 0;

    public short Short() => BinaryPrimitives.ReadInt16BigEndian(Take(2));

    public int Int() => BinaryPrimitives.ReadInt32BigEndian(Take(4));

    public long Long() => BinaryPrimitives.ReadInt64BigEndian(Take(8));

    public float Float() => BitConverter.Int32BitsToSingle(Int());

    public double Double() => BitConverter.Int64BitsToDouble(Long());

    public Guid Uuid() => new(Take(16), bigEndian: true);

    /// <summary>A network NBT text component (unnamed root) as plain text: "text", "translate" with its "with" arguments, then "extra".</summary>
    public string TextComponent()
    {
        var type = Byte();
        return Nbt.Text(Nbt.Read(this, type));
    }
}

public static class Nbt
{
    public static object? Read(McReader r, byte type) => type switch
    {
        0 => null,
        1 => (sbyte)r.Byte(),
        2 => r.Short(),
        3 => r.Int(),
        4 => r.Long(),
        5 => r.Float(),
        6 => r.Double(),
        7 => r.Take(r.Int()).ToArray(),
        8 => Encoding.UTF8.GetString(r.Take((ushort)r.Short())), // NBT strings: unsigned short length, modified UTF-8 (UTF-8 for text)
        9 => ReadList(r),
        10 => ReadCompound(r),
        11 => Enumerable.Range(0, r.Int()).Select(_ => r.Int()).ToArray(),
        12 => Enumerable.Range(0, r.Int()).Select(_ => r.Long()).ToArray(),
        _ => throw new InvalidDataException($"unknown NBT tag {type}"),
    };

    private static List<object?> ReadList(McReader r)
    {
        var type = r.Byte();
        var n = r.Int();
        var list = new List<object?>(Math.Max(0, n));
        for (var i = 0; i < n; i++)
            list.Add(Read(r, type));
        return list;
    }

    private static Dictionary<string, object?> ReadCompound(McReader r)
    {
        var map = new Dictionary<string, object?>(StringComparer.Ordinal);
        while (true)
        {
            var type = r.Byte();
            if (type == 0)
                return map;
            var name = Encoding.UTF8.GetString(r.Take((ushort)r.Short()));
            map[name] = Read(r, type);
        }
    }

    /// <summary>Plain text of a text component value. Translation keys show their arguments (the keys themselves are not translated here).</summary>
    public static string Text(object? component)
    {
        switch (component)
        {
            case string s:
                return s;
            case List<object?> list:
                return string.Concat(list.Select(Text));
            case Dictionary<string, object?> c:
                var sb = new StringBuilder();
                if (c.TryGetValue("text", out var t) || c.TryGetValue("", out t))
                    sb.Append(Text(t));
                if (c.TryGetValue("translate", out var key))
                {
                    var args = c.TryGetValue("with", out var with) && with is List<object?> w ? w.Select(Text).ToList() : [];
                    sb.Append(key switch
                    {
                        "chat.type.text" when args.Count == 2 => $"<{args[0]}> {args[1]}",
                        "chat.type.announcement" when args.Count == 2 => $"[{args[0]}] {args[1]}",
                        _ when args.Count > 0 => string.Join(" ", args),
                        _ => Text(key),
                    });
                }
                if (c.TryGetValue("extra", out var extra))
                    sb.Append(Text(extra));
                return sb.ToString();
            default:
                return component?.ToString() ?? "";
        }
    }

    /// <summary>A plain string as a network NBT text component (String tag), for tests and fake servers.</summary>
    public static byte[] StringComponent(string text)
    {
        var bytes = Encoding.UTF8.GetBytes(text);
        var result = new byte[3 + bytes.Length];
        result[0] = 8;
        BinaryPrimitives.WriteUInt16BigEndian(result.AsSpan(1), (ushort)bytes.Length);
        bytes.CopyTo(result, 3);
        return result;
    }
}

/// <summary>Packet framing: [length][id][data], or with compression [length][data length (0 = not compressed)][zlib(id + data)].</summary>
public sealed class McConnection(Stream stream) : IAsyncDisposable
{
    private readonly SemaphoreSlim writeGate = new(1, 1);

    /// <summary>-1 = no compression; else packets of at least this many bytes are compressed.</summary>
    public int CompressionThreshold { get; set; } = -1;

    private async Task<int> ReadVarIntAsync(CancellationToken ct)
    {
        var result = 0;
        var one = new byte[1];
        for (var shift = 0; shift < 35; shift += 7)
        {
            await stream.ReadExactlyAsync(one, ct).ConfigureAwait(false);
            result |= (one[0] & 0x7F) << shift;
            if ((one[0] & 0x80) == 0)
                return result;
        }
        throw new InvalidDataException("VarInt too long");
    }

    public async Task<(int Id, McReader Data)> ReadAsync(CancellationToken ct)
    {
        var length = await ReadVarIntAsync(ct).ConfigureAwait(false);
        if (length is <= 0 or > 2_097_152)
            throw new InvalidDataException($"packet length {length} out of range");
        var raw = new byte[length];
        await stream.ReadExactlyAsync(raw, ct).ConfigureAwait(false);
        var r = new McReader(raw);
        if (CompressionThreshold >= 0)
        {
            var dataLength = r.VarInt();
            if (dataLength > 0)
            {
                using var input = new MemoryStream(raw, raw.Length - r.Remaining, r.Remaining);
                using var z = new ZLibStream(input, CompressionMode.Decompress);
                var inflated = new byte[dataLength];
                await z.ReadExactlyAsync(inflated, ct).ConfigureAwait(false);
                r = new McReader(inflated);
            }
        }
        return (r.VarInt(), r);
    }

    public async Task WriteAsync(int id, McWriter body, CancellationToken ct)
    {
        var payload = new McWriter().VarInt(id).Bytes(body.ToArray()).ToArray();
        byte[] frame;
        if (CompressionThreshold < 0)
        {
            frame = new McWriter().VarInt(payload.Length).Bytes(payload).ToArray();
        }
        else if (payload.Length < CompressionThreshold)
        {
            var inner = new McWriter().VarInt(0).Bytes(payload).ToArray();
            frame = new McWriter().VarInt(inner.Length).Bytes(inner).ToArray();
        }
        else
        {
            using var compressed = new MemoryStream();
            using (var z = new ZLibStream(compressed, CompressionLevel.Fastest, leaveOpen: true))
                z.Write(payload);
            var inner = new McWriter().VarInt(payload.Length).Bytes(compressed.ToArray()).ToArray();
            frame = new McWriter().VarInt(inner.Length).Bytes(inner).ToArray();
        }
        await writeGate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            await stream.WriteAsync(frame, ct).ConfigureAwait(false);
            await stream.FlushAsync(ct).ConfigureAwait(false);
        }
        finally
        {
            writeGate.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        await stream.DisposeAsync().ConfigureAwait(false);
        writeGate.Dispose();
    }
}
