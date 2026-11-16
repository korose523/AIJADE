using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;

namespace Aijade.Server.Product;

// Speech on this machine through the loopback services of the author's MOSAIC project (ADR-003, migration batch 1), for the
// gateway's "speech", "transcription" and "alignment" sections with "kind": "local":
//   speech         POST {upstream}/tts {"text", "emotion"} → audio/wav (MOSAIC tools/tts_neural.py: VoxCPM2 with one fixed
//                  voice, or Qwen3-TTS). The emotion is one of MOSAIC's four and sets the tone of the voice, as it sets her
//                  face there; AIJADE's stage expression is mapped to it through the shared companion contract.
//   transcription  POST {upstream}/transcribe {"wav_b64", "language"} → {"text", "language", "audio_s"} (MOSAIC
//                  tools/asr_server.py, Qwen3-ASR). The audio is a WAV of at most 4 MiB; the language is one of the
//                  recognizer's names, or "auto".
//   alignment      POST {upstream}/align {"text", "wav_b64"} → {"engine", "duration_s", "characters": [{"char", "start_s",
//                  "end_s", "initial", "final"}]} (MOSAIC tools/align_server.py, Qwen3-ForcedAligner): each Chinese character
//                  of a spoken reply timed, with its strict pinyin initial and final, for the stage's mouth. Only this kind
//                  exists for alignment.
// The services take no key and listen on 127.0.0.1 only, so the route's keys are not used. The formats and limits are those
// of MOSAIC r601 (tools/tts_neural.py, tools/asr_server.py, and tools/align_server.py as of r322), read without changing
// MOSAIC.

public static class LocalVoice
{
    public const string Kind = "local";

    /// <summary>Longest text the local voice speaks (tts_neural.py MAX_CHARS).</summary>
    public const int MaxChars = 2000;

    /// <summary>Largest WAV the local recognizer takes (asr_server.py MAX_WAV_BYTES: two minutes of 16 kHz mono 16-bit).</summary>
    public const int MaxWavBytes = 4 << 20;

    /// <summary>Largest WAV the local aligner takes (align_server.py MAX_WAV_BYTES); its text limit is <see cref="MaxChars"/>.</summary>
    public const int MaxAlignWavBytes = 24 << 20;

    /// <summary>
    /// AIJADE's stage expressions as MOSAIC's emotions: the shared companion contract's mapping
    /// (configs/companion/contract.json, expressions.aijadeToMosaic). An expression without a counterpart is neutral.
    /// </summary>
    public static IReadOnlyDictionary<string, string> Emotions { get; } = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["joy"] = "happy", ["calm"] = "calm", ["curious"] = "curious",
        ["sad"] = "neutral", ["angry"] = "neutral", ["surprised"] = "neutral", ["shy"] = "neutral", ["thinking"] = "neutral", ["sleepy"] = "neutral",
    };

    public static string Emotion(string? expression) => expression is not null && Emotions.TryGetValue(expression, out var e) ? e : "neutral";

    /// <summary>
    /// The recognizer's language for a BCP 47 tag: Chinese, Cantonese (yue, zh-HK, zh-MO), English, Japanese or Korean;
    /// anything else, or no tag, is left to the recognizer ("auto").
    /// </summary>
    public static string Language(string? tag)
    {
        var t = (tag ?? "").Trim().ToLowerInvariant();
        if (t.StartsWith("yue", StringComparison.Ordinal) || t is "zh-hk" or "zh-mo" || t.StartsWith("zh-hant-hk", StringComparison.Ordinal))
            return "Cantonese";
        return (t.Split('-', '_')[0]) switch
        {
            "zh" => "Chinese",
            "en" => "English",
            "ja" => "Japanese",
            "ko" => "Korean",
            _ => "auto",
        };
    }

    public static bool IsWav(byte[] audio) =>
        audio.Length >= 12 && audio.AsSpan(0, 4).SequenceEqual("RIFF"u8) && audio.AsSpan(8, 4).SequenceEqual("WAVE"u8);

    public static async Task<SynthesizedSpeech> SpeakAsync(HttpClient http, GatewayRoute route, string text, string emotion, CancellationToken ct)
    {
        if (text.Length > MaxChars)
            throw ApiException.BadRequest($"the local voice speaks at most {MaxChars} characters", "INVALID_SPEECH_REQUEST");
        // Exactly these two fields: the service refuses anything else.
        var body = new JsonObject { ["text"] = text, ["emotion"] = emotion };
        using var res = await PostAsync(http, route, "/tts", body, ct).ConfigureAwait(false);
        if (res.StatusCode == HttpStatusCode.BadRequest)
            throw ApiException.BadRequest($"the local voice refused the text{await DetailAsync(res, ct).ConfigureAwait(false)}", "INVALID_SPEECH_REQUEST");
        if (!res.IsSuccessStatusCode)
            throw new ApiException(502, "UPSTREAM_ERROR", $"The local voice failed ({(int)res.StatusCode}{await DetailAsync(res, ct).ConfigureAwait(false)})");
        return new SynthesizedSpeech(await res.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false), "audio/wav");
    }

    public static async Task<string> TranscribeAsync(HttpClient http, GatewayRoute route, byte[] audio, string? language, CancellationToken ct)
    {
        if (!IsWav(audio) || audio.Length > MaxWavBytes)
            throw ApiException.BadRequest("the local recognizer takes a WAV of at most 4 MiB", "INVALID_TRANSCRIPTION_REQUEST");
        var body = new JsonObject { ["wav_b64"] = Convert.ToBase64String(audio), ["language"] = Language(language) };
        using var res = await PostAsync(http, route, "/transcribe", body, ct).ConfigureAwait(false);
        if (res.StatusCode == HttpStatusCode.BadRequest)
            throw ApiException.BadRequest($"the local recognizer refused the audio{await DetailAsync(res, ct).ConfigureAwait(false)}", "INVALID_TRANSCRIPTION_REQUEST");
        if (!res.IsSuccessStatusCode)
            throw new ApiException(502, "UPSTREAM_ERROR", $"the local recognizer failed ({(int)res.StatusCode}{await DetailAsync(res, ct).ConfigureAwait(false)})");
        var json = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
        return json?["text"] is JsonValue v && v.TryGetValue<string>(out var text) ? text : "";
    }

    /// <summary>
    /// The characters of a spoken reply timed in its audio: {"durationS", "characters": [{"character", "startS", "endS",
    /// "initial", "final"}]}. Rows without a usable time are left out.
    /// </summary>
    public static async Task<JsonObject> AlignAsync(HttpClient http, GatewayRoute route, string text, byte[] audio, CancellationToken ct)
    {
        if (text.Trim().Length == 0 || text.Length > MaxChars)
            throw ApiException.BadRequest($"the local aligner takes a text of 1-{MaxChars} characters", "INVALID_ALIGNMENT_REQUEST");
        if (!IsWav(audio) || audio.Length > MaxAlignWavBytes)
            throw ApiException.BadRequest("the local aligner takes a WAV of at most 24 MiB", "INVALID_ALIGNMENT_REQUEST");
        // Exactly these two fields: the service refuses anything else.
        var body = new JsonObject { ["text"] = text, ["wav_b64"] = Convert.ToBase64String(audio) };
        using var res = await PostAsync(http, route, "/align", body, ct).ConfigureAwait(false);
        if (res.StatusCode == HttpStatusCode.BadRequest)
            throw ApiException.BadRequest($"the local aligner refused the request{await DetailAsync(res, ct).ConfigureAwait(false)}", "INVALID_ALIGNMENT_REQUEST");
        if (!res.IsSuccessStatusCode)
            throw new ApiException(502, "UPSTREAM_ERROR", $"the local aligner failed ({(int)res.StatusCode}{await DetailAsync(res, ct).ConfigureAwait(false)})");
        var json = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
        static double? Number(JsonNode? n) => n is JsonValue v && v.TryGetValue<double>(out var d) && double.IsFinite(d) ? d : null;
        static string Text(JsonNode? n) => n is JsonValue v && v.TryGetValue<string>(out var s) ? s : "";
        var characters = new JsonArray();
        foreach (var row in json?["characters"] as JsonArray ?? [])
        {
            if (row is JsonObject r && Number(r["start_s"]) is { } start && Number(r["end_s"]) is { } end && start >= 0 && end > start)
                characters.Add(new JsonObject { ["character"] = Text(r["char"]), ["startS"] = start, ["endS"] = end, ["initial"] = Text(r["initial"]), ["final"] = Text(r["final"]) });
        }
        return new JsonObject { ["durationS"] = Number(json?["duration_s"]) ?? 0, ["characters"] = characters };
    }

    private static async Task<HttpResponseMessage> PostAsync(HttpClient http, GatewayRoute route, string path, JsonObject body, CancellationToken ct)
    {
        try
        {
            return await http.PostAsync(new Uri(route.Upstream + path), new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"), ct).ConfigureAwait(false);
        }
        catch (HttpRequestException e)
        {
            throw new ApiException(502, "UPSTREAM_ERROR", $"The local voice service at {route.Upstream} cannot be reached ({e.Message})");
        }
    }

    /// <summary>The service's own explanation ({"error": "..."}), shortened, or nothing.</summary>
    private static async Task<string> DetailAsync(HttpResponseMessage res, CancellationToken ct)
    {
        try
        {
            var error = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false))?["error"]?.GetValue<string>();
            return string.IsNullOrWhiteSpace(error) ? "" : ": " + (error.Length > 200 ? error[..200] : error);
        }
        catch (Exception e) when (e is System.Text.Json.JsonException or InvalidOperationException)
        {
            return "";
        }
    }
}
