using System.Security.Cryptography;
using System.Text.Json;

namespace Aijade.Integrations;

/// <summary>
/// Stable storage boundaries for a channel audience. Private keys keep their existing data; group keys never fall back
/// to the old person-only namespace, whose records do not establish whether the original audience was private or public.
/// </summary>
public static class ChannelScope
{
    /// <summary>Group history belongs to a room; private history retains its existing conversation key.</summary>
    public static string Conversation(ChannelMessage message) => message.IsDirect
        ? $"{message.Platform}:{message.ConversationId}"
        : "group-chat:" + Digest(message.Platform, message.ConversationId);

    /// <summary>Recall and recording share an audience boundary, with each group speaker kept separate.</summary>
    public static string Memory(ChannelMessage message) => message.IsDirect
        ? $"bot:{message.Platform}:{message.AuthorId}"
        : "group-memory:" + Digest(message.Platform, message.ConversationId, message.AuthorId);

    /// <summary>Fallback notebooks separate a person's private relationship and each group/character context.</summary>
    public static string Companion(ChannelMessage message, string characterId) => message.IsDirect
        ? $"{message.Platform}:{message.AuthorId}:{characterId}"
        : "group-companion:" + Digest(message.Platform, message.ConversationId, message.AuthorId, characterId);

    // A JSON tuple keeps identifiers containing colons or Unicode unambiguous. Hashes contain no file/path characters.
    private static string Digest(params string[] parts) => Convert.ToHexStringLower(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(parts)));
}
