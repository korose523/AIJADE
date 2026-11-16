using System.Text.Json.Nodes;

using Aijade.Client.Api;

namespace Aijade.Client.Companion;

/// <summary>Explicit media requests in the same chat, with an actual stored result before any delivery claim.</summary>
public static class CompanionMediaTurn
{
    public static bool IsRequest(string text) =>
        CompanionMedia.Command(text, "/photo", "拍照") is not null || CompanionMedia.Command(text, "/sing", "唱歌") is not null ||
        CompanionMedia.Command(text, "/diary", "日记") is not null ||
        text.Trim() is "/life" or "看看日常" or "/relationship" or "看看关系";

    public static async Task<StoredMessage?> TryAsync(AijadeApi api, CompanionExperience companion, string chatId, string text, bool drawing, bool audio = true, CancellationToken ct = default)
    {
        if (!companion.Profile.Enabled)
            return null;
        var photo = CompanionMedia.Command(text, "/photo", "拍照");
        var song = CompanionMedia.Command(text, "/sing", "唱歌");
        var diary = CompanionMedia.Command(text, "/diary", "日记");
        var life = text.Trim() is "/life" or "看看日常";
        var relationship = text.Trim() is "/relationship" or "看看关系";
        if (photo is null && song is null && diary is null && !life && !relationship)
            return null;
        await api.AppendMessageAsync(chatId, "user", text, ct: ct).ConfigureAwait(false);
        if (diary is not null)
            return await api.AppendMessageAsync(chatId, "assistant", await DiaryReplyAsync(api, companion, chatId, diary, ct).ConfigureAwait(false),
                new JsonObject { ["companionDiary"] = true }, ct).ConfigureAwait(false);
        string reply;
        JsonObject? meta = null;
        if (song is not null)
        {
            var selected = audio ? CompanionMedia.Song((await companion.Notebook.ReadAsync(ct: ct).ConfigureAwait(false)).Assets, song) : null;
            var asset = selected is null ? null : await companion.Notebook.AssetAsync(selected.Id, ct).ConfigureAwait(false);
            reply = audio ? CompanionMedia.SongReply(asset) : "这个聊天渠道暂时不能发送歌声，可以到网页或 QQ 聊天听。";
            if (asset is not null)
                meta = new JsonObject { ["audio"] = new JsonObject { ["source"] = asset.Data, ["title"] = asset.Name, ["attribution"] = asset.Attribution } };
            else if (audio)
            {
                try
                {
                    var wav = await api.SingAsync(song, ct).ConfigureAwait(false);
                    meta = new JsonObject { ["audio"] = new JsonObject { ["source"] = "data:audio/wav;base64," + Convert.ToBase64String(wav), ["title"] = song, ["attribution"] = "configured local singing service" } };
                    reply = $"唱一小段《{song}》给你听。";
                }
                catch (AijadeApiException e) when (e.Code is "GATEWAY_UNCONFIGURED" or "SONG_UNAVAILABLE")
                {
                    reply = CompanionMedia.SongReply(null);
                }
                catch (Exception e) when (!ct.IsCancellationRequested && e is AijadeApiException or HttpRequestException or OperationCanceledException)
                {
                    reply = "歌声服务这次没有接通，稍后再试吧。";
                }
            }
        }
        else
        {
            var snapshot = await companion.SnapshotAsync(ct).ConfigureAwait(false);
            if (photo is not null && drawing)
            {
                var kind = photo.Trim() switch { "landscape" or "风景" => "landscape", "snapshot" or "随手拍" => "snapshot", _ => "selfie" };
                try
                {
                    var image = await api.GenerateImageAsync(CompanionWorld.PhotoPrompt(kind, companion.Profile, snapshot.Moment, snapshot.Weather), ct: ct).ConfigureAwait(false);
                    var moment = snapshot.Moment;
                    var caption = $"虚拟日常照片 · {moment.LocalTime:MM-dd HH:mm} · {moment.Place} · {moment.Outfit?.Description ?? moment.Outfit?.Name ?? "日常便服"}";
                    return await api.AppendMessageAsync(chatId, "assistant", caption, new JsonObject
                    {
                        ["image"] = new JsonObject { ["id"] = image.Id, ["mime"] = image.Mime, ["prompt"] = caption },
                        ["companionPhoto"] = new JsonObject { ["kind"] = kind, ["moment"] = moment.Id, ["generated"] = true },
                    }, ct).ConfigureAwait(false);
                }
                catch (Exception e) when (!ct.IsCancellationRequested && e is AijadeApiException or HttpRequestException)
                {
                    reply = "这次照片没有生成成功，稍后再试吧。";
                }
            }
            else if (photo is not null)
                reply = "照片还没有接通。打开绘图功能并配置图像服务后，我再拍给你。";
            else if (life)
                reply = snapshot.Moment.Describe() + "。" + (snapshot.Weather?.Describe() ?? "还没有可用的真实天气。");
            else
                reply = $"我们现在是{snapshot.Relationship.Stage}的关系，好感度 {snapshot.Relationship.Affection:F1}/100。{snapshot.Relationship.Reason}。";
        }
        return await api.AppendMessageAsync(chatId, "assistant", reply, meta, ct).ConfigureAwait(false);
    }

    private static async Task<string> DiaryReplyAsync(AijadeApi api, CompanionExperience companion, string chatId, string command, CancellationToken ct)
    {
        if (companion.Notebook is not ICompanionDiary diary)
            return "这个角色还没有接通共享日记，请先使用服务端同步的陪伴设置。";
        if (command.Equals("save", StringComparison.OrdinalIgnoreCase) || command == "保存")
        {
            var messages = (await api.MessagesAsync(chatId, ct: ct).ConfigureAwait(false)).Where(m => m.Role is "user" or "assistant").ToList();
            for (var i = messages.Count - 1; i > 0; i--)
            {
                var reply = messages[i]; var user = messages[i - 1];
                if (reply.Role != "assistant" || user.Role != "user" || IsRequest(user.Content) || reply.Meta?.ContainsKey("initiative") == true || reply.Meta?.ContainsKey("reminder") == true)
                    continue;
                var saved = await diary.SaveExchangeAsync(user.Id, reply.Id, ct).ConfigureAwait(false);
                return "这段对话已加入共同日记，可在网页和已绑定的 QQ 中查看。\n\n" + CompanionDiary.Describe(saved);
            }
            return "还没有可保存的完整对话。先聊完一轮，再发送 /diary save。";
        }
        if (command.Length == 0)
            return CompanionDiary.Describe(await diary.ReadDiaryAsync(ct: ct).ConfigureAwait(false));
        if (CompanionDiary.TryDay(command, out var day))
            return CompanionDiary.Describe(await diary.ReadDiaryAsync(day, ct).ConfigureAwait(false));
        return "发送 /diary 查看今天，/diary yyyy-MM-dd 查看指定日期，/diary save 保存最近一段完整对话。保存的摘录会与已绑定 QQ 共享，原聊天记录仍分开。";
    }
}
