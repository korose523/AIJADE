using System.Buffers.Binary;
using System.Net.Sockets;
using System.Text;
using System.Text.Json.Nodes;

namespace Aijade.Server.Tools;

/// <summary>
/// The Source RCON protocol Factorio servers speak (enable with --rcon-port / --rcon-password): little-endian packets
/// [size][id][type][body\0][\0]. Requests: 3 authenticates, 2 runs a command. Replies: 2 answers authentication (id -1 =
/// wrong password; some servers first send an empty type-0 packet), 0 carries a command's output under the request's id.
/// </summary>
public sealed class RconClient(string host, int port, string password) : IAsyncDisposable
{
    private const int Auth = 3;
    private const int AuthResponse = 2;
    private const int Exec = 2;
    private TcpClient? tcp;
    private NetworkStream? stream;
    private int nextId = 1;

    public static byte[] Packet(int id, int type, string body)
    {
        var payload = Encoding.UTF8.GetBytes(body);
        var packet = new byte[4 + 4 + 4 + payload.Length + 2];
        BinaryPrimitives.WriteInt32LittleEndian(packet, packet.Length - 4);
        BinaryPrimitives.WriteInt32LittleEndian(packet.AsSpan(4), id);
        BinaryPrimitives.WriteInt32LittleEndian(packet.AsSpan(8), type);
        payload.CopyTo(packet, 12);
        return packet;
    }

    public static async Task<(int Id, int Type, string Body)> ReadPacketAsync(Stream s, CancellationToken ct)
    {
        var head = new byte[4];
        await s.ReadExactlyAsync(head, ct).ConfigureAwait(false);
        var size = BinaryPrimitives.ReadInt32LittleEndian(head);
        if (size is < 10 or > 1_048_576)
            throw new InvalidDataException($"RCON packet size {size} is out of range");
        var rest = new byte[size];
        await s.ReadExactlyAsync(rest, ct).ConfigureAwait(false);
        return (BinaryPrimitives.ReadInt32LittleEndian(rest), BinaryPrimitives.ReadInt32LittleEndian(rest.AsSpan(4)), Encoding.UTF8.GetString(rest, 8, size - 10));
    }

    private async Task<NetworkStream> ConnectAsync(CancellationToken ct)
    {
        if (stream is not null)
            return stream;
        tcp = new TcpClient();
        await tcp.ConnectAsync(host, port, ct).ConfigureAwait(false);
        var s = tcp.GetStream();
        var id = nextId++;
        await s.WriteAsync(Packet(id, Auth, password), ct).ConfigureAwait(false);
        while (true)
        {
            var (replyId, type, _) = await ReadPacketAsync(s, ct).ConfigureAwait(false);
            if (type != AuthResponse)
                continue; // the empty response some servers send first
            if (replyId == -1)
                throw new UnauthorizedAccessException("RCON password rejected");
            break;
        }
        return stream = s;
    }

    public async Task<string> ExecuteAsync(string command, CancellationToken ct)
    {
        try
        {
            var s = await ConnectAsync(ct).ConfigureAwait(false);
            var id = nextId++;
            await s.WriteAsync(Packet(id, Exec, command), ct).ConfigureAwait(false);
            while (true)
            {
                var (replyId, _, body) = await ReadPacketAsync(s, ct).ConfigureAwait(false);
                if (replyId == id)
                    return body;
            }
        }
        catch (Exception e) when (e is IOException or SocketException or InvalidDataException)
        {
            await DisposeAsync().ConfigureAwait(false); // reconnect next time
            throw;
        }
    }

    public ValueTask DisposeAsync()
    {
        stream?.Dispose();
        tcp?.Dispose();
        stream = null;
        tcp = null;
        return ValueTask.CompletedTask;
    }
}

/// <summary>
/// Factorio through RCON: who is online, the game time, and messages to players. Arbitrary console commands (including
/// Lua via /c, which disables achievements and can change the save) are offered only when the administrator sets
/// allowCommands.
/// </summary>
public sealed class FactorioTools(string host, int port, string password, bool allowCommands) : IToolProvider
{
    private readonly RconClient rcon = new(host, port, password);

    public Task<IReadOnlyList<ToolSpec>> ListAsync(CancellationToken ct)
    {
        var tools = new List<ToolSpec>
        {
            new("players", "Who is playing on the Factorio server right now.", new JsonObject { ["type"] = "object", ["properties"] = new JsonObject() }),
            new("game_time", "The current in-game time of the Factorio server.", new JsonObject { ["type"] = "object", ["properties"] = new JsonObject() }),
            new("say", "Say something to everyone on the Factorio server (as a chat message).", new JsonObject
            {
                ["type"] = "object",
                ["properties"] = new JsonObject { ["message"] = new JsonObject { ["type"] = "string" } },
                ["required"] = new JsonArray("message"),
            }),
        };
        if (allowCommands)
        {
            tools.Add(new("command", "Run a Factorio console command (e.g. /evolution).", new JsonObject
            {
                ["type"] = "object",
                ["properties"] = new JsonObject { ["command"] = new JsonObject { ["type"] = "string" } },
                ["required"] = new JsonArray("command"),
            }));
        }
        return Task.FromResult<IReadOnlyList<ToolSpec>>(tools);
    }

    public async Task<ToolCallOutcome> CallAsync(string tool, JsonObject arguments, CancellationToken ct) => tool switch
    {
        "players" => new(await rcon.ExecuteAsync("/players online", ct).ConfigureAwait(false), false),
        "game_time" => new(await rcon.ExecuteAsync("/time", ct).ConfigureAwait(false), false),
        // A plain line (not starting with '/') is a chat message from the server; a leading '/' is neutralised.
        "say" => new(await rcon.ExecuteAsync((arguments["message"]?.GetValue<string>() ?? "").TrimStart('/').ReplaceLineEndings(" "), ct).ConfigureAwait(false) is { Length: > 0 } r ? r : "Said.", false),
        "command" when allowCommands => new(await rcon.ExecuteAsync(arguments["command"]?.GetValue<string>() ?? "", ct).ConfigureAwait(false), false),
        _ => new($"unknown Factorio tool '{tool}'", true),
    };

    public ValueTask DisposeAsync() => rcon.DisposeAsync();
}
