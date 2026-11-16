using System.Text.Json;

using Aijade.Client.Settings;

namespace Aijade.Client.Companion;

/// <summary>
/// The reminders of this device's chats (ADR-003): one JSON document per account in the platform key-value store (browser
/// localStorage, MAUI preferences), beside the settings. No server table is added: the server's migration count is a number
/// one of the manuscripts reports. Pending and claimed reminders are kept, closed ones for a week.
/// </summary>
public sealed class ReminderStore(IKeyValueStore store, Func<string> account)
{
    public const string KeyPrefix = "aijade.reminders.";
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    private string Key => KeyPrefix + account();

    public async Task<ReminderBook> LoadAsync()
    {
        var json = await store.GetAsync(Key).ConfigureAwait(false);
        if (string.IsNullOrEmpty(json))
            return new ReminderBook();
        try
        {
            return new ReminderBook(JsonSerializer.Deserialize<List<Reminder>>(json, Json) ?? []);
        }
        catch (JsonException)
        {
            return new ReminderBook(); // a document this version cannot read is started afresh, not shown as an error
        }
    }

    public async Task SaveAsync(ReminderBook book, double now) =>
        await store.SetAsync(Key, JsonSerializer.Serialize(book.Kept(now), Json)).ConfigureAwait(false);
}
