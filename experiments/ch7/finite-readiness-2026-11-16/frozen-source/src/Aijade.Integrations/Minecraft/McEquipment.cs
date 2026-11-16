namespace Aijade.Integrations.Minecraft;

public static partial class McBlocks
{
    /// <summary>The block a block-state id belongs to (states of one block are contiguous); null for an unknown id.</summary>
    public static string? Name(int state)
    {
        if (state < 0 || state > FirstState[^1] + 4096)
            return null;
        var i = Array.BinarySearch(FirstState, state);
        if (i < 0)
            i = ~i - 1;
        return i >= 0 ? Names[i] : null;
    }

    /// <summary>The tool that breaks a block fastest ("pickaxe", "axe", "shovel" or "hoe"); null when the hand is as good.</summary>
    public static string? ToolFor(string? block)
    {
        if (block is null)
            return null;
        if (block.EndsWith("_log", StringComparison.Ordinal) || block.EndsWith("_wood", StringComparison.Ordinal)
            || block.EndsWith("_planks", StringComparison.Ordinal) || block.EndsWith("_stem", StringComparison.Ordinal)
            || block.EndsWith("_hyphae", StringComparison.Ordinal) || block is "crafting_table" or "chest" or "barrel" or "bookshelf" or "ladder")
            return "axe";
        if (block is "dirt" or "grass_block" or "sand" or "red_sand" or "gravel" or "clay" or "snow" or "snow_block" or "mud" or "soul_sand"
            or "soul_soil" or "coarse_dirt" or "rooted_dirt" or "podzol" or "mycelium" or "farmland" or "dirt_path")
            return "shovel";
        if (block.EndsWith("_leaves", StringComparison.Ordinal) || block is "hay_block" or "sponge" or "moss_block" or "sculk")
            return "hoe";
        if (block.Contains("stone", StringComparison.Ordinal) || block.EndsWith("_ore", StringComparison.Ordinal)
            || block.Contains("deepslate", StringComparison.Ordinal) || block.Contains("brick", StringComparison.Ordinal)
            || block is "netherrack" or "obsidian" or "andesite" or "diorite" or "granite" or "tuff" or "calcite" or "basalt" or "furnace"
            || block.EndsWith("_block", StringComparison.Ordinal) && (block.StartsWith("iron", StringComparison.Ordinal)
                || block.StartsWith("gold", StringComparison.Ordinal) || block.StartsWith("diamond", StringComparison.Ordinal)
                || block.StartsWith("copper", StringComparison.Ordinal) || block.StartsWith("coal", StringComparison.Ordinal)))
            return "pickaxe";
        return null;
    }
}

public static partial class McItems
{
    private static readonly Dictionary<string, string> MaterialZh = new(StringComparer.Ordinal)
    {
        ["leather"] = "皮革", ["golden"] = "金", ["chainmail"] = "锁链", ["copper"] = "铜", ["iron"] = "铁", ["turtle"] = "海龟",
        ["diamond"] = "钻石", ["netherite"] = "下界合金", ["wooden"] = "木", ["stone"] = "石",
    };

    private static readonly Dictionary<string, string> PieceZh = new(StringComparer.Ordinal)
    {
        ["helmet"] = "头盔", ["chestplate"] = "胸甲", ["leggings"] = "护腿", ["boots"] = "靴子",
        ["pickaxe"] = "镐", ["axe"] = "斧", ["shovel"] = "铲", ["hoe"] = "锄", ["sword"] = "剑",
    };

    /// <summary>A spoken Chinese name for armour and tools ("iron_helmet" → 铁头盔); other items keep their registry name.</summary>
    public static string ChineseName(string item)
    {
        var i = item.IndexOf('_', StringComparison.Ordinal);
        return i > 0 && MaterialZh.TryGetValue(item[..i], out var m) && PieceZh.TryGetValue(item[(i + 1)..], out var p) ? m + p : item;
    }
}

public static class McGear
{
    private static readonly string[] Tiers = ["wooden", "leather", "golden", "stone", "chainmail", "copper", "iron", "turtle", "diamond", "netherite"];

    /// <summary>Quality of a tool or armour piece by its material (higher is better); −1 for an item that is neither.</summary>
    public static int Tier(string item)
    {
        var material = item[..Math.Max(0, item.IndexOf('_', StringComparison.Ordinal))];
        return Array.IndexOf(Tiers, material);
    }

    /// <summary>The player-inventory slot an armour item is worn in (5 head, 6 chest, 7 legs, 8 feet); null when it is not armour.</summary>
    public static int? ArmorSlot(string item) => item switch
    {
        _ when item.EndsWith("_helmet", StringComparison.Ordinal) => 5,
        _ when item.EndsWith("_chestplate", StringComparison.Ordinal) => 6,
        _ when item.EndsWith("_leggings", StringComparison.Ordinal) => 7,
        _ when item.EndsWith("_boots", StringComparison.Ordinal) => 8,
        _ => null,
    };

    /// <summary>The kind of tool an item is ("pickaxe", "axe", "shovel", "hoe", "sword"); null when it is no tool.</summary>
    public static string? ToolKind(string item)
    {
        foreach (var kind in new[] { "pickaxe", "shovel", "sword", "hoe", "axe" })
        {
            if (item.EndsWith("_" + kind, StringComparison.Ordinal))
                return kind;
        }
        return null;
    }

    /// <summary>
    /// The armour moves that would improve what is worn: for each armour slot, the best piece in the inventory (slots 9–44)
    /// when it beats the worn one. Pure, so the choice can be tested without a server.
    /// </summary>
    public static IReadOnlyList<(int From, int ArmorSlot, string Item)> ArmorUpgrades(Func<int, (int Item, int Count)> slot)
    {
        var moves = new List<(int, int, string)>();
        for (var armor = 5; armor <= 8; armor++)
        {
            var worn = slot(armor);
            var wornTier = worn.Item >= 0 ? Tier(McItems.Name(worn.Item)) : -2;
            (int From, string Item, int Tier)? best = null;
            for (var s = 9; s <= 44; s++)
            {
                var (item, count) = slot(s);
                if (item < 0 || count <= 0)
                    continue;
                var name = McItems.Name(item);
                if (ArmorSlot(name) != armor)
                    continue;
                var t = Tier(name);
                if (t > wornTier && (best is null || t > best.Value.Tier))
                    best = (s, name, t);
            }
            if (best is { } b)
                moves.Add((b.From, armor, b.Item));
        }
        return moves;
    }

    /// <summary>The inventory slot (9–44) holding the best tool of a kind; null when there is none.</summary>
    public static int? BestTool(string kind, Func<int, (int Item, int Count)> slot)
    {
        int? best = null;
        var bestTier = -2;
        for (var s = 9; s <= 44; s++)
        {
            var (item, count) = slot(s);
            if (item < 0 || count <= 0)
                continue;
            var name = McItems.Name(item);
            if (ToolKind(name) != kind)
                continue;
            var t = Tier(name);
            if (t > bestTier)
                (best, bestTier) = (s, t);
        }
        return best;
    }
}

public sealed partial class McClient
{
    private const int Swap = 2;

    private async Task ClickAsync(int slot, int button, int mode, CancellationToken ct)
    {
        int state;
        lock (stateIds)
            state = stateIds.GetValueOrDefault(0);
        // no predicted slots and an empty cursor: the server applies the click and resyncs the changed slots
        await connection!.WriteAsync(SContainerClick, new McWriter().VarInt(0).VarInt(state).Short((short)slot).Byte((byte)button).VarInt(mode).VarInt(0).Bool(false), ct)
            .ConfigureAwait(false);
        await Task.Delay(150, ct).ConfigureAwait(false);
    }

    /// <summary>
    /// Put on the best armour in the inventory: a worn piece that is beaten is shift-clicked back into the inventory first,
    /// then the better one is shift-clicked, which the server moves to its armour slot. Returns the items now worn.
    /// </summary>
    public async Task<IReadOnlyList<string>> EquipArmorAsync(CancellationToken ct)
    {
        var worn = new List<string>();
        foreach (var (from, armorSlot, item) in McGear.ArmorUpgrades(s => Slot(0, s)))
        {
            // each click waits for the server's slot update, so a slow server does not make the next step read stale slots
            if (Slot(0, armorSlot).Item >= 0)
            {
                await ClickAsync(armorSlot, 0, QuickMove, ct).ConfigureAwait(false);
                if (!await WaitForSlotsAsync(() => Slot(0, armorSlot).Item < 0, ct).ConfigureAwait(false))
                    continue; // the inventory is full: the worn piece stays
            }
            await ClickAsync(from, 0, QuickMove, ct).ConfigureAwait(false);
            if (await WaitForSlotsAsync(() => Slot(0, armorSlot).Item >= 0 && McItems.Name(Slot(0, armorSlot).Item) == item, ct).ConfigureAwait(false))
                worn.Add(item);
        }
        return worn;
    }

    private static async Task<bool> WaitForSlotsAsync(Func<bool> condition, CancellationToken ct)
    {
        var until = DateTimeOffset.UtcNow.AddSeconds(2);
        while (!condition())
        {
            if (DateTimeOffset.UtcNow >= until)
                return false;
            await Task.Delay(50, ct).ConfigureAwait(false);
        }
        return true;
    }

    /// <summary>
    /// Hold the best tool for breaking a block: a hotbar tool is selected; one in the main inventory is swapped into the
    /// selected hotbar slot. Returns the tool's name, or null when no suitable tool is carried (the hand is used).
    /// </summary>
    public async Task<string?> HoldToolForAsync(BlockPos block, CancellationToken ct)
    {
        var kind = McBlocks.ToolFor(McBlocks.Name(World.BlockAt(block)));
        if (kind is null || McGear.BestTool(kind, s => Slot(0, s)) is not { } at)
            return null;
        var name = McItems.Name(Slot(0, at).Item);
        if (at >= 36)
            await SelectSlotAsync(at - 36, ct).ConfigureAwait(false);
        else
            await ClickAsync(at, SelectedSlot, Swap, ct).ConfigureAwait(false);
        return name;
    }
}
