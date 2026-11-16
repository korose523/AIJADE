using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Providers.Llm;

namespace Aijade.Client.Chat;

// Vision: the companion sees what the user chooses to show it. Frames (a shared screen, the camera, or an image the user
// attaches) are described by a vision-capable model through the gateway; the description, not the image, becomes context
// for the chat model, so any chat model can take part. Nothing is captured unless the user starts sharing.

public enum VisionSource
{
    Screen,
    Camera,
    Attachment,
}

/// <summary>Turns one frame into a short description with a vision-capable model.</summary>
public sealed class VisionInterpreter(AijadeApi api, Func<string> model)
{
    public const int MaxTokens = 300;

    public static string Instruction(VisionSource source) => source switch
    {
        VisionSource.Screen =>
            "This is the user's screen right now. In at most four sentences, say what they are doing and anything a companion chatting with them might want to know. Do not guess at text you cannot read.",
        VisionSource.Camera =>
            "This is the user's camera right now. In at most three sentences, describe the scene and the person's apparent activity and mood, without identifying anyone.",
        _ => "The user shared this image in a chat. Describe it in at most four sentences, including any text in it that matters.",
    };

    /// <summary>The OpenAI-format message carrying the instruction and the image (a data: URL).</summary>
    public static JsonArray Messages(string imageDataUrl, VisionSource source) =>
        new(new JsonObject
        {
            ["role"] = "user",
            ["content"] = new JsonArray(
                new JsonObject { ["type"] = "text", ["text"] = Instruction(source) },
                new JsonObject { ["type"] = "image_url", ["image_url"] = new JsonObject { ["url"] = imageDataUrl } }),
        });

    public async Task<string> DescribeAsync(string imageDataUrl, VisionSource source, CancellationToken ct = default)
    {
        if (!imageDataUrl.StartsWith("data:image/", StringComparison.Ordinal))
            throw new ArgumentException("expected a data:image/… URL", nameof(imageDataUrl));
        var raw = await api.CompleteChatAsync(model(), Messages(imageDataUrl, source), MaxTokens, ct: ct).ConfigureAwait(false);
        var text = ChatParsing.ParseCompletion(raw, model()).Text.Trim();
        return text.Length == 0 ? throw new AijadeApiException(502, "EMPTY_VISION_RESULT", "The vision model returned no description") : text;
    }
}

/// <summary>
/// What the companion currently sees, as context for the next turn: the latest look at the shared screen or camera while it
/// is fresh, and an attached image exactly once (for the turn it was attached to).
/// </summary>
public sealed class VisionContext(Func<bool> enabled, TimeProvider? time = null) : IContextProvider
{
    /// <summary>A look older than this is no longer "what the user is doing".</summary>
    public static TimeSpan Freshness { get; } = TimeSpan.FromMinutes(2);

    private readonly TimeProvider clock = time ?? TimeProvider.System;
    private readonly object gate = new();
    private (VisionSource Source, string Text, DateTimeOffset At)? live;
    private string? attachment;

    public void Observe(VisionSource source, string description)
    {
        lock (gate)
        {
            if (source == VisionSource.Attachment)
                attachment = description;
            else
                live = (source, description, clock.GetUtcNow());
        }
    }

    /// <summary>Forget everything, including a pending attachment (sign-out).</summary>
    public void Clear()
    {
        lock (gate)
        {
            live = null;
            attachment = null;
        }
    }

    /// <summary>Forget the live view (sharing stopped).</summary>
    public void ClearLive()
    {
        lock (gate)
            live = null;
    }

    public DateTimeOffset? LastLook
    {
        get
        {
            lock (gate)
                return live?.At;
        }
    }

    public Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct)
    {
        if (!enabled())
            return Task.FromResult<string?>(null);
        var parts = new List<string>();
        lock (gate)
        {
            if (attachment is not null)
            {
                parts.Add($"The user attached an image to this message. It shows: {attachment}");
                attachment = null;
            }
            if (live is { } l && clock.GetUtcNow() - l.At <= Freshness)
            {
                var ago = (int)(clock.GetUtcNow() - l.At).TotalSeconds;
                parts.Add($"What you can see on the user's {(l.Source == VisionSource.Camera ? "camera" : "screen")} ({ago} s ago): {l.Text}");
            }
        }
        return Task.FromResult<string?>(parts.Count == 0 ? null : string.Join("\n\n", parts));
    }
}
