using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace Aijade.Server.Tools;

// A Mi Cloud session (account login,
// HMAC-signed API calls, as implemented by the open-source micloud / python-miio clients), Mi Home device operations via
// the cloud RPC relay with the legacy miIO commands that Yeelight-style lights and plugs understand, and the companion's
// tools. Devices that only speak the MIoT spec protocol reject these commands; that error is returned, never reported as
// success. Accounts that need a captcha or two-factor confirmation cannot log in this way, and say so. There is no scene
// tool: an earlier version claimed to run scenes without calling any API, and the author removed it.

public sealed record MiCredentials(string Username, string Password, string Region);

public sealed class MiCloudException(string message, string? code = null) : Exception(message)
{
    public string? Code { get; } = code;
}

public sealed class MiCloud(MiCredentials credentials, HttpClient http, TimeProvider time)
{
    public static IReadOnlyDictionary<string, string> RegionHosts { get; } = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["cn"] = "https://api.io.mi.com/app", ["de"] = "https://de.api.io.mi.com/app", ["i2"] = "https://i2.api.io.mi.com/app",
        ["ru"] = "https://ru.api.io.mi.com/app", ["sg"] = "https://sg.api.io.mi.com/app", ["us"] = "https://us.api.io.mi.com/app",
    };

    private const string LoginBase = "https://account.xiaomi.com/pass";
    private const string ResponsePrefix = "&&&START&&&";
    private (string UserId, string Ssecurity, string ServiceToken)? session;

    public string ApiBase { get; } = RegionHosts.TryGetValue(credentials.Region, out var b)
        ? b : throw new MiCloudException($"Unknown Mi Cloud region \"{credentials.Region}\". Use one of: {string.Join(", ", RegionHosts.Keys)}.");

    /// <summary>Upper-case hex MD5, the form serviceLoginAuth2 expects.</summary>
#pragma warning disable CA5351 // MD5 is what the Mi account protocol requires here; it is not used for security of our own.
    public static string PasswordHash(string password) => Convert.ToHexString(MD5.HashData(Encoding.UTF8.GetBytes(password)));
#pragma warning restore CA5351

    /// <summary>8 random bytes then the big-endian minute counter, base64.</summary>
    public static string Nonce(long nowMs, byte[] random)
    {
        var bytes = new byte[12];
        random.AsSpan(0, 8).CopyTo(bytes);
        System.Buffers.Binary.BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(8), (uint)(nowMs / 60_000));
        return Convert.ToBase64String(bytes);
    }

    /// <summary>base64(sha256(b64decode(ssecurity) ‖ b64decode(nonce))).</summary>
    public static string SignedNonce(string ssecurity, string nonce) =>
        Convert.ToBase64String(SHA256.HashData([.. Convert.FromBase64String(ssecurity), .. Convert.FromBase64String(nonce)]));

    /// <summary>base64(hmac_sha256(b64decode(signedNonce), "path&amp;signedNonce&amp;nonce&amp;data=json")).</summary>
    public static string Signature(string path, string signedNonce, string nonce, string data) =>
        Convert.ToBase64String(HMACSHA256.HashData(Convert.FromBase64String(signedNonce), Encoding.UTF8.GetBytes(string.Join('&', path, signedNonce, nonce, $"data={data}"))));

    private static JsonObject Prefixed(string text)
    {
        var body = text.StartsWith(ResponsePrefix, StringComparison.Ordinal) ? text[ResponsePrefix.Length..] : text;
        try
        {
            return JsonNode.Parse(body) as JsonObject ?? throw new MiCloudException($"Unexpected Mi account response: {body[..Math.Min(120, body.Length)]}");
        }
        catch (System.Text.Json.JsonException)
        {
            throw new MiCloudException($"Unexpected Mi account response: {body[..Math.Min(120, body.Length)]}");
        }
    }

    private static string? Cookie(HttpResponseMessage res, string name) =>
        res.Headers.TryGetValues("Set-Cookie", out var lines)
            ? lines.Select(l => l.Split(';')[0].Trim()).FirstOrDefault(c => c.StartsWith(name + "=", StringComparison.Ordinal))?[(name.Length + 1)..]
            : null;

    public async Task LoginAsync(CancellationToken ct)
    {
        using var step1Req = new HttpRequestMessage(HttpMethod.Get, $"{LoginBase}/serviceLogin?sid=xiaomiio&_json=true");
        step1Req.Headers.Add("Cookie", $"userId={Uri.EscapeDataString(credentials.Username)}");
        using var step1 = await http.SendAsync(step1Req, ct).ConfigureAwait(false);
        var sign = Prefixed(await step1.Content.ReadAsStringAsync(ct).ConfigureAwait(false))["_sign"]?.GetValue<string>()
            ?? throw new MiCloudException("Mi account login step 1 returned no _sign.");
        using var step2 = await http.PostAsync($"{LoginBase}/serviceLoginAuth2", new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["sid"] = "xiaomiio", ["hash"] = PasswordHash(credentials.Password), ["callback"] = "https://sts.api.io.mi.com/sts",
            ["qs"] = "%3Fsid%3Dxiaomiio%26_json%3Dtrue", ["user"] = credentials.Username, ["_sign"] = sign, ["_json"] = "true",
        }), ct).ConfigureAwait(false);
        var auth = Prefixed(await step2.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
        if (auth["notificationUrl"] is not null || auth["captchaUrl"] is not null)
            throw new MiCloudException("Mi account requires captcha or two-factor verification; complete it in the Mi Home app or browser first.", "verification-required");
        if (auth["code"]?.GetValue<int>() != 0 || auth["ssecurity"]?.GetValue<string>() is not { } ssecurity || auth["location"]?.GetValue<string>() is not { } location)
            throw new MiCloudException($"Mi account login failed: {auth["desc"] ?? auth["description"] ?? "invalid credentials"}", auth["code"]?.ToString());
        using var step3 = await http.GetAsync(location, ct).ConfigureAwait(false);
        var serviceToken = Cookie(step3, "serviceToken") ?? throw new MiCloudException("Mi account login step 3 returned no serviceToken.");
        session = (auth["userId"]!.ToString(), ssecurity, serviceToken);
    }

    /// <summary>Signed POST to an /app/* endpoint (e.g. /home/device_list); returns "result".</summary>
    public async Task<JsonNode?> RequestAsync(string path, JsonObject data, CancellationToken ct)
    {
        if (session is null)
            await LoginAsync(ct).ConfigureAwait(false);
        var (userId, ssecurity, serviceToken) = session!.Value;
        var payload = data.ToJsonString();
        var nonce = Nonce(time.GetUtcNow().ToUnixTimeMilliseconds(), RandomNumberGenerator.GetBytes(8));
        var signed = SignedNonce(ssecurity, nonce);
        using var req = new HttpRequestMessage(HttpMethod.Post, $"{ApiBase}{path}")
        {
            Content = new FormUrlEncodedContent(new Dictionary<string, string> { ["signature"] = Signature(path, signed, nonce, payload), ["_nonce"] = nonce, ["data"] = payload }),
        };
        req.Headers.Add("x-xiaomi-protocal-flag-cli", "PROTOCAL-HTTP2");
        req.Headers.Add("Cookie", $"userId={userId}; yetAnotherServiceToken={serviceToken}; serviceToken={serviceToken}; locale=en_GB; channel=MI_APP_STORE");
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        if (res.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
        {
            session = null;
            throw new MiCloudException($"Mi Cloud rejected the session ({(int)res.StatusCode}); it will log in again on the next call.", ((int)res.StatusCode).ToString(CultureInfo.InvariantCulture));
        }
        var body = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
        if (body?["code"]?.GetValue<int>() != 0)
            throw new MiCloudException($"Mi Cloud {path} failed: {body?["message"]?.ToString() ?? $"code {body?["code"]}"}", body?["code"]?.ToString());
        return body["result"];
    }
}

public sealed record XiaomiDevice(string Did, string Name, string Model, string Type, bool IsOnline);

public class XiaomiClient(MiCloud cloud)
{
    private static readonly (string Hint, string Type)[] TypeHints =
        [("gateway", "gateway"), ("plug", "outlet"), ("light", "light"), ("lamp", "light"), ("bulb", "light"), ("sensor", "sensor"), ("curtain", "curtain"),
         ("airpurifier", "airpurifier"), ("vacuum", "vacuum"), ("camera", "camera"), ("lock", "lock"), ("switch", "switch")];

    public static string DeviceType(string model) => TypeHints.FirstOrDefault(h => model.Contains(h.Hint, StringComparison.OrdinalIgnoreCase)).Type ?? "other";

    private static int Clamp(double v, int lo, int hi) => (int)Math.Clamp(Math.Round(v, MidpointRounding.AwayFromZero), lo, hi);

    public virtual async Task<IReadOnlyList<XiaomiDevice>> DevicesAsync(CancellationToken ct) =>
        [.. ((await cloud.RequestAsync("/home/device_list", new JsonObject { ["getVirtualModel"] = false, ["getHuamiDevices"] = 0 }, ct).ConfigureAwait(false))?["list"] as JsonArray ?? [])
            .Select(d => new XiaomiDevice(d!["did"]!.ToString(), d["name"]?.ToString() ?? d["did"]!.ToString(), d["model"]?.ToString() ?? "", DeviceType(d["model"]?.ToString() ?? ""),
                d["isOnline"]?.GetValue<bool>() != false))];

    /// <summary>A miIO command relayed through the cloud; a device-side error is a failure, not a success.</summary>
    public virtual async Task<JsonNode?> RpcAsync(string did, string method, JsonArray parameters, CancellationToken ct)
    {
        var result = await cloud.RequestAsync($"/home/rpc/{Uri.EscapeDataString(did)}", new JsonObject { ["method"] = method, ["params"] = parameters }, ct).ConfigureAwait(false);
        if (result is JsonObject o && o.ContainsKey("error"))
            throw new MiCloudException($"Device {did} rejected {method}: {o["error"]?.ToJsonString()}");
        return result;
    }

    public async Task<JsonObject> StatusAsync(string did, CancellationToken ct)
    {
        string[] props = ["power", "bright", "ct", "rgb"];
        var values = await RpcAsync(did, "get_prop", new JsonArray([.. props.Select(p => (JsonNode)p)]), ct).ConfigureAwait(false) as JsonArray ?? [];
        return new JsonObject([.. props.Select((p, i) => KeyValuePair.Create(p, i < values.Count ? values[i]?.DeepClone() : null))]);
    }

    public Task ToggleAsync(string did, bool on, CancellationToken ct) => RpcAsync(did, "set_power", new JsonArray(on ? "on" : "off"), ct);

    public Task BrightnessAsync(string did, double percent, CancellationToken ct) => RpcAsync(did, "set_bright", new JsonArray(Clamp(percent, 1, 100)), ct);

    public Task ColorTemperatureAsync(string did, double kelvin, CancellationToken ct) => RpcAsync(did, "set_ct_abx", new JsonArray(Clamp(kelvin, 1700, 6500), "smooth", 500), ct);

    public Task ColorAsync(string did, double r, double g, double b, CancellationToken ct) =>
        RpcAsync(did, "set_rgb", new JsonArray((Clamp(r, 0, 255) << 16) | (Clamp(g, 0, 255) << 8) | Clamp(b, 0, 255), "smooth", 500), ct);
}

public sealed class XiaomiTools(XiaomiClient client) : IToolProvider
{
    private static JsonObject Target(params (string Name, JsonObject Schema, bool Required)[] extra)
    {
        var props = new JsonObject
        {
            ["did"] = new JsonObject { ["type"] = "string", ["description"] = "Device id from list_devices." },
            ["name"] = new JsonObject { ["type"] = "string", ["description"] = "Device name (exact or a unique part of it)." },
        };
        foreach (var (name, schema, _) in extra)
            props[name] = schema;
        return new JsonObject { ["type"] = "object", ["properties"] = props, ["required"] = new JsonArray([.. extra.Where(e => e.Required).Select(e => (JsonNode)e.Name)]) };
    }

    private static JsonObject Number(double min, double max) => new() { ["type"] = "number", ["minimum"] = min, ["maximum"] = max };

    public Task<IReadOnlyList<ToolSpec>> ListAsync(CancellationToken ct) => Task.FromResult<IReadOnlyList<ToolSpec>>(
    [
        new("list_devices", "List devices bound to the Mi Home account with model, type and online state.", new JsonObject { ["type"] = "object", ["properties"] = new JsonObject() }),
        new("get_device_status", "Read power, brightness, colour temperature and colour of a light or plug.", Target()),
        new("toggle_device", "Switch a light or plug on or off.", Target(("on", new JsonObject { ["type"] = "boolean", ["description"] = "true to switch on." }, true))),
        new("set_brightness", "Set brightness of a light in percent (1-100).", Target(("brightness", Number(1, 100), true))),
        new("set_color_temperature", "Set colour temperature of a light in kelvin (1700-6500).", Target(("temperature", Number(1700, 6500), true))),
        new("set_color", "Set an RGB colour (each channel 0-255) on a colour light.", Target(("r", Number(0, 255), true), ("g", Number(0, 255), true), ("b", Number(0, 255), true))),
    ]);

    /// <summary>By exact did, exact name, or a unique partial name.</summary>
    public static XiaomiDevice Find(IReadOnlyList<XiaomiDevice> devices, JsonObject a)
    {
        if (a["did"]?.GetValue<string>() is { Length: > 0 } did)
            return devices.FirstOrDefault(d => d.Did == did) ?? throw new ArgumentException($"No device with did {did}.");
        var name = a["name"]?.GetValue<string>()?.Trim() ?? "";
        if (name.Length == 0)
            throw new ArgumentException("Provide either did or name.");
        if (devices.FirstOrDefault(d => d.Name == name) is { } exact)
            return exact;
        var partial = devices.Where(d => d.Name.Contains(name, StringComparison.Ordinal)).ToList();
        return partial.Count switch
        {
            1 => partial[0],
            > 1 => throw new ArgumentException($"\"{name}\" matches several devices: {string.Join(", ", partial.Select(d => d.Name))}. Use the full name or did."),
            _ => throw new ArgumentException($"No device named \"{name}\"."),
        };
    }

    private static double Num(JsonObject a, string key) =>
        a[key] is JsonValue v && v.GetValueKind() == System.Text.Json.JsonValueKind.Number
            && double.TryParse(v.ToJsonString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var d) && double.IsFinite(d)
            ? d : throw new ArgumentException($"{key} must be a number.");

    public async Task<ToolCallOutcome> CallAsync(string tool, JsonObject arguments, CancellationToken ct)
    {
        var a = arguments;
        if (tool == "list_devices")
            return new(string.Join("\n", (await client.DevicesAsync(ct).ConfigureAwait(false)).Select(d => $"{d.Name} (did {d.Did}, {d.Model}, {d.Type}, {(d.IsOnline ? "online" : "offline")})")), false);
        var device = Find(await client.DevicesAsync(ct).ConfigureAwait(false), a);
        if (!device.IsOnline)
            return new($"{device.Name} is offline.", true);
        switch (tool)
        {
            case "get_device_status":
                return new($"{device.Name}: {(await client.StatusAsync(device.Did, ct).ConfigureAwait(false)).ToJsonString()}", false);
            case "toggle_device":
                var on = a["on"] is JsonValue v && v.TryGetValue<bool>(out var b) ? b : throw new ArgumentException("on must be true or false.");
                await client.ToggleAsync(device.Did, on, ct).ConfigureAwait(false);
                return new($"{device.Name} switched {(on ? "on" : "off")}.", false);
            case "set_brightness":
                var brightness = Num(a, "brightness");
                await client.BrightnessAsync(device.Did, brightness, ct).ConfigureAwait(false);
                return new($"{device.Name} brightness {brightness}%.", false);
            case "set_color_temperature":
                var kelvin = Num(a, "temperature");
                await client.ColorTemperatureAsync(device.Did, kelvin, ct).ConfigureAwait(false);
                return new($"{device.Name} colour temperature {kelvin} K.", false);
            case "set_color":
                var (r, g, bl) = (Num(a, "r"), Num(a, "g"), Num(a, "b"));
                await client.ColorAsync(device.Did, r, g, bl, ct).ConfigureAwait(false);
                return new($"{device.Name} colour rgb({r}, {g}, {bl}).", false);
            default:
                return new($"unknown Mi Home tool '{tool}'", true);
        }
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;
}
