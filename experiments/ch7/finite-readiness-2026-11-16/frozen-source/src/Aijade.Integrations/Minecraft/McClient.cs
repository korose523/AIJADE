using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;

namespace Aijade.Integrations.Minecraft;

/// <summary>A line of chat seen in game. <see cref="Private"/>: a whisper to the bot (/msg). Sender null = a server message.</summary>
public sealed record McChat(string? Sender, string Text, bool Private)
{
    /// <summary>The sender's UUID for player chat (to find them in the world); null for system and disguised chat.</summary>
    public Guid? SenderId { get; init; }
}

/// <summary>
/// A Minecraft: Java Edition player client, protocol 777 (Java Edition 26.3), offline mode only (no Mojang account login,
/// so no encryption): handshake → login → configuration → play, answering keep-alives, pings and teleports, reporting chat
/// and health, and sending chat. Chat is sent unsigned, so the server must have enforce-secure-profile=false.
/// </summary>
public sealed partial class McClient(string host, int port, string name) : IAsyncDisposable
{
    public const int Protocol = 777;

    // Packet ids by state and direction (Java Edition 26.3).
    private const int CLoginDisconnect = 0x00, CEncryptionRequest = 0x01, CLoginSuccess = 0x02, CSetCompression = 0x03, CLoginPluginRequest = 0x04;
    private const int SLoginStart = 0x00, SLoginPluginResponse = 0x02, SLoginAcknowledged = 0x03;
    private const int CConfigDisconnect = 0x02, CConfigFinish = 0x03, CConfigKeepAlive = 0x04, CConfigPing = 0x05, CConfigKnownPacks = 0x0F;
    private const int SClientInformation = 0x00, SConfigFinishAck = 0x03, SConfigKeepAlive = 0x04, SConfigPong = 0x05, SConfigKnownPacks = 0x07;
    private const int CDisconnect = 0x20, CDisguisedChat = 0x21, CKeepAlive = 0x2D, CLogin = 0x32, CPing = 0x3E, CPlayerChat = 0x42, CPosition = 0x49,
        CSetHealth = 0x6A, CStartConfiguration = 0x78, CSystemChat = 0x7C;
    private const int SConfirmTeleport = 0x00, SChatCommand = 0x07, SChat = 0x09, SClientCommand = 0x0C, SKeepAlive = 0x1C, SConfigurationAck = 0x10, SPlayerLoaded = 0x2C, SPong = 0x2D;

    private TcpClient? tcp;
    private McConnection? connection;
    private double x, y, z;
    private float yaw, pitch;
    private bool loaded;

    public event Action<McChat>? Chat;

    public event Action<float, int>? Health;

    public event Action? Joined;

    public string Name => name;

    /// <summary>The UUID offline-mode servers give a name (version 3, from "OfflinePlayer:" + name).</summary>
    public static Guid OfflineUuid(string playerName)
    {
#pragma warning disable CA5351 // MD5 is what the offline-mode UUID derivation is defined with; it protects nothing here.
        var hash = MD5.HashData(Encoding.UTF8.GetBytes("OfflinePlayer:" + playerName));
#pragma warning restore CA5351
        hash[6] = (byte)((hash[6] & 0x0F) | 0x30);
        hash[8] = (byte)((hash[8] & 0x3F) | 0x80);
        return new Guid(hash, bigEndian: true);
    }

    public async Task ConnectAsync(CancellationToken ct)
    {
        tcp = new TcpClient { NoDelay = true };
        await tcp.ConnectAsync(host, port, ct).ConfigureAwait(false);
        connection = new McConnection(tcp.GetStream());
        await connection.WriteAsync(0x00, new McWriter().VarInt(Protocol).String(host).UShort((ushort)port).VarInt(2), ct).ConfigureAwait(false);
        await connection.WriteAsync(SLoginStart, new McWriter().String(name).Uuid(OfflineUuid(name)), ct).ConfigureAwait(false);
        while (true)
        {
            var (id, r) = await connection.ReadAsync(ct).ConfigureAwait(false);
            switch (id)
            {
                case CLoginDisconnect:
                    throw new InvalidOperationException($"the server refused the login: {r.String()}");
                case CEncryptionRequest:
                    throw new NotSupportedException("the server is in online mode; this bot joins offline-mode servers (online-mode=false) only");
                case CSetCompression:
                    connection.CompressionThreshold = r.VarInt();
                    break;
                case CLoginPluginRequest:
                    await connection.WriteAsync(SLoginPluginResponse, new McWriter().VarInt(r.VarInt()).Bool(false), ct).ConfigureAwait(false);
                    break;
                case CLoginSuccess:
                    await connection.WriteAsync(SLoginAcknowledged, new McWriter(), ct).ConfigureAwait(false);
                    await ConfigureAsync(ct).ConfigureAwait(false);
                    return;
            }
        }
    }

    private async Task ConfigureAsync(CancellationToken ct)
    {
        var c = connection!;
        await c.WriteAsync(SClientInformation, new McWriter().String("en_us").Byte(2).VarInt(0).Bool(true).Byte(0x7F).VarInt(1).Bool(false).Bool(true).VarInt(0), ct).ConfigureAwait(false);
        while (true)
        {
            var (id, r) = await c.ReadAsync(ct).ConfigureAwait(false);
            switch (id)
            {
                case CConfigKnownPacks:
                    // Knowing no packs, the server sends the registries in full.
                    await c.WriteAsync(SConfigKnownPacks, new McWriter().VarInt(0), ct).ConfigureAwait(false);
                    break;
                case CConfigKeepAlive:
                    await c.WriteAsync(SConfigKeepAlive, new McWriter().Long(r.Long()), ct).ConfigureAwait(false);
                    break;
                case CConfigPing:
                    await c.WriteAsync(SConfigPong, new McWriter().Int(r.Int()), ct).ConfigureAwait(false);
                    break;
                case CConfigDisconnect:
                    throw new InvalidOperationException($"disconnected during configuration: {r.TextComponent()}");
                case CConfigFinish:
                    await c.WriteAsync(SConfigFinishAck, new McWriter(), ct).ConfigureAwait(false);
                    return;
            }
        }
    }

    /// <summary>Process the game until disconnected or cancelled.</summary>
    public async Task RunAsync(CancellationToken ct)
    {
        var c = connection ?? throw new InvalidOperationException("connect first");
        while (true)
        {
            // cancellation always ends the loop with OperationCanceledException, also when it lands between two packets
            ct.ThrowIfCancellationRequested();
            var (id, r) = await c.ReadAsync(ct).ConfigureAwait(false);
            switch (id)
            {
                case CKeepAlive:
                    await c.WriteAsync(SKeepAlive, new McWriter().Long(r.Long()), ct).ConfigureAwait(false);
                    break;
                case CPing:
                    await c.WriteAsync(SPong, new McWriter().Int(r.Int()), ct).ConfigureAwait(false);
                    break;
                case CLogin:
                    Joined?.Invoke();
                    break;
                case CPosition:
                    await PositionAsync(r, ct).ConfigureAwait(false);
                    break;
                case CSystemChat:
                    var text = r.TextComponent();
                    if (!r.Bool() && text.Length > 0)
                        Chat?.Invoke(new McChat(null, text, false));
                    break;
                case CPlayerChat:
                    Chat?.Invoke(PlayerChat(r));
                    break;
                case CDisguisedChat:
                    var message = r.TextComponent();
                    if (r.VarInt() == 0)
                        throw new NotSupportedException("inline chat types are not supported");
                    Chat?.Invoke(new McChat(r.TextComponent(), message, false));
                    break;
                case CSetHealth:
                    var health = r.Float();
                    Health?.Invoke(health, r.VarInt());
                    if (health <= 0) // dead (also after rejoining dead): respawn, as the death screen's button does
                        await c.WriteAsync(SClientCommand, new McWriter().VarInt(0), ct).ConfigureAwait(false);
                    break;
                case CDisconnect:
                    throw new InvalidOperationException($"disconnected: {r.TextComponent()}");
                default:
                    await WorldPacketAsync(id, r, ct).ConfigureAwait(false);
                    break;
                case CStartConfiguration:
                    await c.WriteAsync(SConfigurationAck, new McWriter(), ct).ConfigureAwait(false);
                    await ConfigureAsync(ct).ConfigureAwait(false);
                    break;
            }
        }
    }

    /// <summary>Player Chat Message: header, body, previous messages, other (unsigned content, filter), formatting.</summary>
    public static McChat PlayerChat(McReader r)
    {
        r.VarInt();      // global index
        var senderId = r.Uuid();
        r.VarInt();      // index
        if (r.Bool())
            r.Take(256); // signature
        var message = r.String();
        r.Long();        // timestamp
        r.Long();        // salt
        var previous = r.VarInt();
        for (var i = 0; i < previous; i++)
        {
            if (r.VarInt() == 0)
                r.Take(256);
        }
        var unsigned = r.Bool() ? r.TextComponent() : null;
        if (r.VarInt() == 2) // partially filtered: BitSet
        {
            var longs = r.VarInt();
            r.Take(longs * 8);
        }
        if (r.VarInt() == 0)
            throw new NotSupportedException("inline chat types are not supported");
        var sender = r.TextComponent();
        var target = r.Bool() ? r.TextComponent() : null;
        return new McChat(sender, unsigned ?? message, target is not null) { SenderId = senderId };
    }

    private async Task PositionAsync(McReader r, CancellationToken ct)
    {
        var teleport = r.VarInt();
        double nx = r.Double(), ny = r.Double(), nz = r.Double();
        r.Double();
        r.Double();
        r.Double();
        float nyaw = r.Float(), npitch = r.Float();
        var flags = r.Int(); // relative: bit 0 x, 1 y, 2 z, 3 yaw, 4 pitch
        lock (motion)
        {
            x = (flags & 1) != 0 ? x + nx : nx;
            y = (flags & 2) != 0 ? y + ny : ny;
            z = (flags & 4) != 0 ? z + nz : nz;
            yaw = (flags & 8) != 0 ? yaw + nyaw : nyaw;
            pitch = (flags & 16) != 0 ? pitch + npitch : npitch;
            teleported = true;
        }
        await connection!.WriteAsync(SConfirmTeleport, new McWriter().VarInt(teleport).Double(x).Double(y).Double(z).Float(yaw).Float(pitch), ct).ConfigureAwait(false);
        if (!loaded)
        {
            loaded = true;
            await connection.WriteAsync(SPlayerLoaded, new McWriter(), ct).ConfigureAwait(false);
        }
    }

    public (double X, double Y, double Z) Position => (x, y, z);

    /// <summary>Say something: chat (split into 256-character messages) or, starting with '/', a command.</summary>
    public async Task SayAsync(string text, CancellationToken ct)
    {
        var c = connection ?? throw new InvalidOperationException("not connected");
        if (text.StartsWith('/'))
        {
            await c.WriteAsync(SChatCommand, new McWriter().String(text[1..]), ct).ConfigureAwait(false);
            return;
        }
        foreach (var part in ChannelText.Split(text.ReplaceLineEndings(" "), 256))
        {
            await c.WriteAsync(SChat, new McWriter().String(part).Long(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Long(Random.Shared.NextInt64())
                .Bool(false).VarInt(0).Bytes([0, 0, 0]).Byte(0), ct).ConfigureAwait(false);
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (connection is not null)
            await connection.DisposeAsync().ConfigureAwait(false);
        tcp?.Dispose();
    }
}

/// <summary>
/// The companion as a player on a Minecraft server: chat that names it (or a whisper) is answered in chat (whispers by
/// whisper). Requests to come, follow, stop, go to, dig or place (see <see cref="MinecraftBehaviour"/>) are carried out in
/// the world instead of being answered by the conversation.
/// </summary>
public sealed class MinecraftConnector(string host, int port, string name) : IChannelConnector
{
    public string Platform => "minecraft";

    public async Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct)
    {
        await using var client = new McClient(host, port, name);
        using var behaviour = new MinecraftBehaviour(client);
        client.Chat += chat =>
        {
            if (chat.Sender is not { } sender || sender == name)
                return;
            var addressed = chat.Private || chat.Text.Contains(name, StringComparison.OrdinalIgnoreCase);
            if (addressed && MinecraftBehaviour.Parse(chat.Text, name) is { } command)
            {
                Task Say(string text) => client.SayAsync(chat.Private ? $"/msg {sender} {text}" : text, ct);
                _ = behaviour.RunAsync(command, chat.SenderId, Say, ct);
                return;
            }
            var message = new ChannelMessage("minecraft", $"{host}:{port}", sender, sender, chat.Text, chat.Private, addressed);
            _ = Task.Run(async () =>
            {
                if (await handle(message, ct).ConfigureAwait(false) is { Text.Length: > 0 } reply)
                    await client.SayAsync(chat.Private ? $"/msg {sender} {reply.Text.ReplaceLineEndings(" ")}" : reply.Text, ct).ConfigureAwait(false);
            }, ct);
        };
        await client.ConnectAsync(ct).ConfigureAwait(false);
        await client.RunAsync(ct).ConfigureAwait(false);
    }
}
