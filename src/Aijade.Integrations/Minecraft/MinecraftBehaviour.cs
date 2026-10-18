using System.Globalization;
using System.Text.RegularExpressions;

namespace Aijade.Integrations.Minecraft;

/// <summary>What a player asked the companion to do in the world.</summary>
public enum McCommandKind
{
    Come,
    Follow,
    Stop,
    GoTo,
    Dig,
    Place,
    Where,
    Collect,
    Attack,
    Craft,
    Equip,
}

public sealed record McCommand(McCommandKind Kind, BlockPos? At = null, bool Chinese = false)
{
    /// <summary>Attack: the creature's entity type and the name it was called by.</summary>
    public (int Type, string Name)? Creature { get; init; }

    /// <summary>Craft: the item ids the spoken name can mean, and how many items were asked for.</summary>
    public IReadOnlyList<int> Items { get; init; } = [];

    public int Count { get; init; } = 1;
}

/// <summary>
/// The companion's skills as a player: come to someone, follow them, stop, walk to coordinates, dig (and pick up what
/// drops, holding the right tool) or place a block, pick up items, attack a creature, craft from the recipe book, put on
/// the best armour it carries, and say where it is; paths may lead through water and up ladders and vines. Commands are recognised in English and Chinese from chat that names the companion; one runs at a
/// time and "stop" cancels it. Everything else in chat goes to the conversation as before.
/// </summary>
public sealed partial class MinecraftBehaviour(McClient client) : IDisposable
{
    private CancellationTokenSource? current;
    private readonly Lock gate = new();

    [GeneratedRegex(@"(-?\d+)[\s,]+(-?\d+)[\s,]+(-?\d+)")]
    private static partial Regex Coordinates();

    private static readonly (McCommandKind Kind, Regex Pattern)[] Patterns =
    [
        (McCommandKind.Stop, new(@"^\s*(stop|halt|stay|wait)\b|^\s*(停下|停止|停|别动|等等)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Follow, new(@"\b(follow( me)?)\b|跟着我|跟我来|跟随我|跟上", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Come, new(@"\b(come( here| over| to me)?)\b|过来|来这里|到我这", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.GoTo, new(@"\b(go|walk|move)( to)?\b|去|走到|前往", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Dig, new(@"\b(dig|mine|break)\b|挖|破坏|拆", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Equip, new(@"\b(equip|gear up|suit up|(wear|put on)( (your|the|some))? (armou?r|gear))\b|穿上?(盔甲|装备|护甲)|装备上|换上装备", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Place, new(@"\b(place|put|build)\b|放置|放|建", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Where, new(@"\bwhere are you\b|你在哪", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Collect, new(@"\b(collect|pick (it |them |things |stuff )?up)\b|捡起来|捡一下|拾取|捡东西", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Attack, new(@"\b(attack|kill|hit|fight)\b|攻击|打|杀", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
        (McCommandKind.Craft, new(@"\b(craft|make)\b|合成|制作|做", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)),
    ];

    private static readonly Dictionary<string, int> NumberWords = new(StringComparer.OrdinalIgnoreCase)
    {
        ["a"] = 1, ["an"] = 1, ["one"] = 1, ["two"] = 2, ["three"] = 3, ["four"] = 4, ["five"] = 5, ["six"] = 6, ["seven"] = 7, ["eight"] = 8,
        ["nine"] = 9, ["ten"] = 10, ["一"] = 1, ["两"] = 2, ["二"] = 2, ["三"] = 3, ["四"] = 4, ["五"] = 5, ["六"] = 6, ["七"] = 7, ["八"] = 8,
        ["九"] = 9, ["十"] = 10,
    };

    [GeneratedRegex(@"\b(\d{1,2})\b|\b(an?|one|two|three|four|five|six|seven|eight|nine|ten)\b|([一两二三四五六七八九十])\s*[个根块把张些]", RegexOptions.IgnoreCase)]
    private static partial Regex Quantity();

    /// <summary>Recognise a command in a chat line addressed to the companion (its name removed first); null when there is none.</summary>
    public static McCommand? Parse(string text, string botName)
    {
        var t = Regex.Replace(text, Regex.Escape(botName), " ", RegexOptions.IgnoreCase).Trim(' ', ',', '，', ':', '：', '!', '！', '.', '。');
        var chinese = t.Any(c => c is >= '一' and <= '鿿');
        var coords = Coordinates().Match(t);
        BlockPos? at = coords.Success
            ? new BlockPos(int.Parse(coords.Groups[1].Value, CultureInfo.InvariantCulture), int.Parse(coords.Groups[2].Value, CultureInfo.InvariantCulture), int.Parse(coords.Groups[3].Value, CultureInfo.InvariantCulture))
            : null;
        foreach (var (kind, pattern) in Patterns)
        {
            if (!pattern.IsMatch(t))
                continue;
            // Moving, digging and placing need a target; without coordinates "go"/"dig"/"place" is just conversation.
            if (kind is McCommandKind.GoTo or McCommandKind.Dig or McCommandKind.Place && at is null)
                continue;
            if (kind == McCommandKind.Attack)
            {
                // only creatures the companion knows; "hit the road" stays conversation
                var creature = McWorld.Creatures.Keys.Where(n => Regex.IsMatch(t, n.All(char.IsAsciiLetter) ? $@"\b{n}s?\b" : Regex.Escape(n), RegexOptions.IgnoreCase))
                    .OrderByDescending(n => n.Length).FirstOrDefault();
                if (creature is null)
                    continue;
                return new McCommand(kind, at, chinese) { Creature = (McWorld.Creatures[creature], creature) };
            }
            if (kind == McCommandKind.Craft)
            {
                // only things that name an item; "what are you doing" (你在做什么) stays conversation
                var items = McItems.Resolve(t);
                if (items.Count == 0)
                    continue;
                var q = Quantity().Match(t);
                var count = !q.Success ? 1 : q.Groups[1].Success ? int.Parse(q.Groups[1].Value, CultureInfo.InvariantCulture) : NumberWords[q.Groups[2].Success ? q.Groups[2].Value : q.Groups[3].Value];
                return new McCommand(kind, null, chinese) { Items = items, Count = Math.Clamp(count, 1, 64) };
            }
            return new McCommand(kind, at, chinese);
        }
        return null;
    }

    /// <summary>Run a command for <paramref name="playerId"/> (the speaker); reports progress through <paramref name="say"/>.</summary>
    public Task RunAsync(McCommand command, Guid? playerId, Func<string, Task> say, CancellationToken ct)
    {
        string T(string en, string zh) => command.Chinese ? zh : en;
        CancellationTokenSource cts;
        lock (gate)
        {
            current?.Cancel();
            current?.Dispose();
            current = null;
            if (command.Kind == McCommandKind.Stop)
                return say(T("Stopping.", "好，我停下了。"));
            if (command.Kind == McCommandKind.Where)
            {
                var (px, py, pz) = client.Position;
                return say(T($"I'm at {px:0} {py:0} {pz:0}.", $"我在 {px:0} {py:0} {pz:0}。"));
            }
            cts = current = CancellationTokenSource.CreateLinkedTokenSource(ct);
        }
        return Task.Run(async () =>
        {
            try
            {
                switch (command.Kind)
                {
                    case McCommandKind.Come:
                        if (Speaker(playerId) is not { } target)
                        {
                            await say(T("I can't see you from here.", "我在这里看不到你。")).ConfigureAwait(false);
                            return;
                        }
                        await say(T("Coming!", "来了！")).ConfigureAwait(false);
                        await say(await client.GoToAsync(BlockPos.Of(target.X, target.Y, target.Z), 2, cts.Token).ConfigureAwait(false)
                            ? T("Here I am.", "我到了。") : T("I can't find a way to you.", "我找不到过去的路。")).ConfigureAwait(false);
                        break;
                    case McCommandKind.Follow:
                        await say(T("Following you.", "我跟着你。")).ConfigureAwait(false);
                        await FollowAsync(playerId, say, T, cts.Token).ConfigureAwait(false);
                        break;
                    case McCommandKind.GoTo:
                        await say(T($"Heading to {command.At}.", $"我去 {command.At}。")).ConfigureAwait(false);
                        await say(await client.GoToAsync(command.At!.Value, 0, cts.Token).ConfigureAwait(false)
                            ? T("Arrived.", "到了。") : T("I can't find a way there.", "我找不到去那里的路。")).ConfigureAwait(false);
                        break;
                    case McCommandKind.Dig:
                        await DigAsync(command.At!.Value, say, T, cts.Token).ConfigureAwait(false);
                        break;
                    case McCommandKind.Place:
                        await PlaceAsync(command.At!.Value, say, T, cts.Token).ConfigureAwait(false);
                        break;
                    case McCommandKind.Collect:
                        var picked = await client.CollectAsync(12, cts.Token).ConfigureAwait(false);
                        await say(picked > 0 ? T($"Picked up {picked} item(s).", $"捡起了 {picked} 样东西。") : T("There is nothing to pick up nearby.", "附近没有可以捡的东西。")).ConfigureAwait(false);
                        break;
                    case McCommandKind.Attack:
                        await AttackAsync(command.Creature!.Value, say, T, cts.Token).ConfigureAwait(false);
                        break;
                    case McCommandKind.Craft:
                        await CraftAsync(command.Items, command.Count, say, T, cts.Token).ConfigureAwait(false);
                        break;
                    case McCommandKind.Equip:
                        var worn = await client.EquipArmorAsync(cts.Token).ConfigureAwait(false);
                        await say(worn.Count > 0
                            ? T($"Now wearing {string.Join(", ", worn.Select(w => w.Replace('_', ' ')))}.", $"穿上了 {string.Join("、", worn.Select(McItems.ChineseName))}。")
                            : T("I have no better armour to put on.", "我身上没有更好的盔甲可以换。")).ConfigureAwait(false);
                        break;
                    default:
                        break;
                }
            }
            catch (OperationCanceledException)
            {
            }
            catch (InvalidOperationException e)
            {
                await say(T($"I couldn't: {e.Message}.", $"做不到：{e.Message}。")).ConfigureAwait(false);
            }
        }, CancellationToken.None);
    }

    private McEntity? Speaker(Guid? playerId) => playerId is { } id ? client.World.EntityByUuid(id) : null;

    private async Task FollowAsync(Guid? playerId, Func<string, Task> say, Func<string, string, string> t, CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            if (Speaker(playerId) is not { } target)
            {
                await say(t("I lost sight of you.", "我看不到你了。")).ConfigureAwait(false);
                return;
            }
            var goal = BlockPos.Of(target.X, target.Y, target.Z);
            var feet = client.Feet;
            if (Math.Sqrt(Math.Pow(feet.X - goal.X, 2) + Math.Pow(feet.Z - goal.Z, 2)) > 3)
            {
                // walk part of the way, then look again: the player keeps moving
                var path = client.World.FindPath(feet, goal, 2);
                if (path is not null)
                    await client.WalkAsync(path.Take(8).ToList(), ct).ConfigureAwait(false);
                else
                    await Task.Delay(1000, ct).ConfigureAwait(false);
            }
            else
            {
                await client.LookAtAsync(target.X, target.Y + 1.6, target.Z, ct).ConfigureAwait(false);
                await Task.Delay(500, ct).ConfigureAwait(false);
            }
        }
    }

    private async Task DigAsync(BlockPos block, Func<string, Task> say, Func<string, string, string> t, CancellationToken ct)
    {
        if (McWorld.IsAir(client.World.BlockAt(block)))
        {
            await say(t($"There is nothing at {block}.", $"{block} 那里什么也没有。")).ConfigureAwait(false);
            return;
        }
        if (!await client.GoToAsync(block, 2, ct).ConfigureAwait(false))
        {
            await say(t("I can't get close enough.", "我走不到够得着的地方。")).ConfigureAwait(false);
            return;
        }
        await client.HoldToolForAsync(block, ct).ConfigureAwait(false);
        if (!await client.DigAsync(block, ct).ConfigureAwait(false))
        {
            await say(t("It won't break.", "挖不动。")).ConfigureAwait(false);
            return;
        }
        // the block drops as an item: go and pick it up
        var picked = await client.CollectAsync(3, ct, block).ConfigureAwait(false);
        await say(picked > 0 ? t($"Dug out {block} and picked it up.", $"挖掉了 {block}，也捡起来了。") : t($"Dug out {block}.", $"挖掉了 {block}。")).ConfigureAwait(false);
    }

    private async Task AttackAsync((int Type, string Name) creature, Func<string, Task> say, Func<string, string, string> t, CancellationToken ct)
    {
        var (px, py, pz) = client.Position;
        var target = client.World.Entities(creature.Type)
            .Select(e => (e, d: Math.Sqrt(Math.Pow(e.X - px, 2) + Math.Pow(e.Y - py, 2) + Math.Pow(e.Z - pz, 2))))
            .Where(x => x.d <= 24).OrderBy(x => x.d).Select(x => x.e).FirstOrDefault();
        if (target is null)
        {
            await say(t($"I don't see a {creature.Name} nearby.", $"附近没有看到{creature.Name}。")).ConfigureAwait(false);
            return;
        }
        await say(t($"Attacking the {creature.Name}!", $"去打{creature.Name}！")).ConfigureAwait(false);
        await say(await client.AttackAsync(target.Id, TimeSpan.FromSeconds(30), ct).ConfigureAwait(false)
            ? t($"The {creature.Name} is gone.", $"{creature.Name}没了。") : t($"I couldn't get the {creature.Name}.", $"没打着{creature.Name}。")).ConfigureAwait(false);
    }

    private async Task PlaceAsync(BlockPos target, Func<string, Task> say, Func<string, string, string> t, CancellationToken ct)
    {
        if (!await client.GoToAsync(target, 3, ct).ConfigureAwait(false))
        {
            await say(t("I can't get close enough.", "我走不到够得着的地方。")).ConfigureAwait(false);
            return;
        }
        // Standing in the spot (for example in the pit just dug)? Step onto the nearest free standing place beside it.
        var feet = client.Feet;
        if (feet == target || feet.Up() == target)
        {
            var aside = Enumerable.Range(-2, 5).SelectMany(dx => Enumerable.Range(-2, 5).SelectMany(dz => Enumerable.Range(-1, 3).Select(dy => target.Offset(dx, dy, dz))))
                .Where(p => p != target && p.Up() != target && p != target.Up() && client.World.CanStand(p))
                .OrderBy(p => Math.Abs(p.X - target.X) + Math.Abs(p.Z - target.Z) + Math.Abs(p.Y - target.Y))
                .FirstOrDefault(p => client.World.FindPath(feet, p, 0, 4000) is not null);
            if (aside == default || !await client.GoToAsync(aside, 0, ct).ConfigureAwait(false))
            {
                await say(t("I can't get out of the way.", "我让不开。")).ConfigureAwait(false);
                return;
            }
        }
        await say(await client.PlaceAsync(target, ct).ConfigureAwait(false)
            ? t($"Placed a block at {target}.", $"在 {target} 放好了。") : t("Nothing was placed — am I holding a block?", "没放上去——我手里有方块吗？")).ConfigureAwait(false);
    }

    private async Task CraftAsync(IReadOnlyList<int> items, int count, Func<string, Task> say, Func<string, string, string> t, CancellationToken ct)
    {
        var name = items.Count == 1 ? McItems.Name(items[0]).Replace('_', ' ') : McItems.Name(items[0]).Split('_').Last();
        var candidates = client.RecipesFor(items);
        if (candidates.Count == 0)
        {
            // the server unlocks recipes as their materials are first picked up
            await say(t($"I don't know how to make {name} yet — it isn't in my recipe book.", $"我还不会做{name}——配方书里没有。")).ConfigureAwait(false);
            return;
        }
        var needTable = false;
        foreach (var recipe in candidates)
        {
            var container = 0;
            if (!recipe.FitsInventory)
            {
                if (client.FindCraftingTable() is not { } table)
                {
                    needTable = true;
                    continue;
                }
                if (!await client.GoToAsync(table, 2, ct).ConfigureAwait(false) || await client.OpenCraftingTableAsync(table, ct).ConfigureAwait(false) is not { } opened)
                {
                    needTable = true;
                    continue;
                }
                container = opened;
            }
            var rounds = (count + Math.Max(1, recipe.ResultCount) - 1) / Math.Max(1, recipe.ResultCount);
            int made;
            try
            {
                made = await client.CraftAsync(recipe, rounds, container, ct).ConfigureAwait(false);
            }
            finally
            {
                if (container != 0)
                    await client.CloseContainerAsync(container, CancellationToken.None).ConfigureAwait(false);
            }
            if (made > 0)
            {
                var total = made * Math.Max(1, recipe.ResultCount);
                var what = McItems.Name(recipe.ResultItem).Replace('_', ' ');
                await say(t($"Made {total} {what}.", $"做好了 {total} 个{what}。")).ConfigureAwait(false);
                return;
            }
        }
        await say(needTable
            ? t($"I need a crafting table nearby to make {name}.", $"做{name}需要附近有工作台。")
            : t($"I don't have the materials for {name}.", $"我没有做{name}的材料。")).ConfigureAwait(false);
    }

    public void Dispose()
    {
        lock (gate)
        {
            current?.Cancel();
            current?.Dispose();
            current = null;
        }
    }
}
