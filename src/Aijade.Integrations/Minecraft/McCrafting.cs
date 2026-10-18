using System.Text.RegularExpressions;

namespace Aijade.Integrations.Minecraft;

/// <summary>An item name as a player says it, resolved to item ids.</summary>
public static partial class McItems
{
    // Lazy: static initialisers of the two partial files run in no guaranteed order, and Names lives in the other one.
    private static readonly Lazy<Dictionary<string, int>> ByName = new(() => Names.Select((n, i) => (n, i)).ToDictionary(p => p.n, p => p.i, StringComparer.Ordinal));

    public static int? Id(string name) => ByName.Value.TryGetValue(name, out var id) ? id : null;

    public static string Name(int id) => id >= 0 && id < Names.Length ? Names[id] : $"item #{id}";

    /// <summary>Spoken Chinese names of common craftable items → item name, or a family suffix starting with '_' (any wood).</summary>
    public static readonly IReadOnlyDictionary<string, string> Chinese = new Dictionary<string, string>
    {
        ["木板"] = "_planks", ["木棍"] = "stick", ["棍子"] = "stick", ["工作台"] = "crafting_table", ["箱子"] = "chest", ["熔炉"] = "furnace",
        ["火把"] = "torch", ["梯子"] = "ladder", ["碗"] = "bowl", ["面包"] = "bread", ["木门"] = "_door", ["栅栏"] = "_fence",
        ["木镐"] = "wooden_pickaxe", ["木斧"] = "wooden_axe", ["木剑"] = "wooden_sword", ["木铲"] = "wooden_shovel", ["木锄"] = "wooden_hoe",
        ["石镐"] = "stone_pickaxe", ["石斧"] = "stone_axe", ["石剑"] = "stone_sword", ["石铲"] = "stone_shovel", ["石锄"] = "stone_hoe",
        ["铁镐"] = "iron_pickaxe", ["铁斧"] = "iron_axe", ["铁剑"] = "iron_sword", ["铁铲"] = "iron_shovel", ["桶"] = "bucket",
    };

    [GeneratedRegex(@"[a-z]+")]
    private static partial Regex Words();

    /// <summary>
    /// Item ids a phrase can mean: a Chinese name, else the longest run of English words that names an item (singular or
    /// plural), else a family ("planks" → every kind of planks). Empty when nothing matches.
    /// </summary>
    public static IReadOnlyList<int> Resolve(string phrase)
    {
        var chinese = Chinese.Keys.Where(phrase.Contains).OrderByDescending(k => k.Length).FirstOrDefault();
        if (chinese is not null)
            return Lookup(Chinese[chinese]);
        var words = Words().Matches(phrase.ToLowerInvariant()).Select(m => m.Value).ToList();
        for (var len = words.Count; len >= 1; len--)
        {
            for (var start = 0; start + len <= words.Count; start++)
            {
                var name = string.Join('_', words.Skip(start).Take(len));
                foreach (var candidate in new[] { name, name.EndsWith("es", StringComparison.Ordinal) ? name[..^2] : null, name.EndsWith('s') ? name[..^1] : null })
                {
                    if (candidate is null || candidate.Length < 3)
                        continue;
                    if (Id(candidate) is { } id)
                        return [id];
                    var family = Lookup("_" + candidate);
                    if (family.Count > 0)
                        return family;
                }
            }
        }
        return [];
    }

    private static List<int> Lookup(string nameOrFamily) => nameOrFamily.StartsWith('_')
        ? [.. Names.Select((n, i) => (n, i)).Where(p => p.n.EndsWith(nameOrFamily, StringComparison.Ordinal)).Select(p => p.i)]
        : Id(nameOrFamily) is { } id ? [id] : [];
}

/// <summary>A recipe the server has put in the player's recipe book (26.3 recipe display).</summary>
public sealed record McRecipe(int DisplayId, int ResultItem, int ResultCount, int Width, int Height, bool Crafting)
{
    /// <summary>Fits the 2×2 grid of the player's own inventory (otherwise a crafting table is needed).</summary>
    public bool FitsInventory => Crafting && Width <= 2 && Height <= 2;
}

// Recipe book and crafting. The server sends the recipes the player has unlocked (Recipe Book Add) as displays: a type, its
// slot displays (themselves a small tagged union) and the result. Crafting is then what the vanilla client does when a
// recipe is clicked in the book: Place Recipe fills the grid from the inventory, and a shift-click (Container Click, quick
// move) on the result slot moves the product into the inventory. The server checks everything; the client only watches the
// result slot to see whether the grid could be filled.
public sealed partial class McClient
{
    private const int COpenScreen = 0x3C, CRecipeBookAdd = 0x4B, CRecipeBookRemove = 0x4C;
    private const int SContainerClick = 0x12, SContainerClose = 0x13, SPlaceRecipe = 0x27;
    private const int QuickMove = 1;

    /// <summary>The crafting table's block state (it has exactly one) in the 26.3 block registry.</summary>
    public const int CraftingTableState = 6866;

    private readonly Dictionary<int, McRecipe> recipes = [];
    private readonly Dictionary<int, int> stateIds = []; // container id → last state id
    private readonly Dictionary<(int Container, int Slot), (int Item, int Count)> slots = [];
    private readonly Dictionary<int, int> containerSizes = []; // container id → slot count (from its last full content)
    private TaskCompletionSource<int>? screenOpened;

    /// <summary>The recipes in the player's recipe book, by display id.</summary>
    public IReadOnlyList<McRecipe> Recipes
    {
        get
        {
            lock (recipes)
                return [.. recipes.Values];
        }
    }

    /// <summary>The item in a slot of a container (0 = the player's inventory), as far as the client knows; (−1, 0) = empty.</summary>
    public (int Item, int Count) Slot(int container, int slot)
    {
        lock (slots)
            return slots.TryGetValue((container, slot), out var s) ? s : (-1, 0);
    }

    /// <summary>How many of an item the player's inventory holds (main inventory and hotbar), as far as the client knows.</summary>
    public int CountInInventory(int item)
    {
        lock (slots)
            return slots.Where(kv => kv.Key.Container == 0 && kv.Key.Slot is >= 9 and <= 45 && kv.Value.Item == item).Sum(kv => kv.Value.Count);
    }

    /// <summary>An item stack: (item, count), (−1, 0) when empty, null when it carries components (unreadable, see ReadStackCount).</summary>
    private static (int Item, int Count)? ReadStack(McReader r)
    {
        var count = r.VarInt();
        if (count <= 0)
            return (-1, 0);
        var item = r.VarInt();
        var added = r.VarInt();
        var removed = r.VarInt();
        if (added > 0)
            return null;
        for (var i = 0; i < removed; i++)
            r.VarInt();
        return (item, count);
    }

    private void TrackSlot(int container, int slot, (int Item, int Count)? stack)
    {
        lock (slots)
        {
            Put(container, slot, stack);
            // Every container screen ends with the player's 27 inventory slots and 9 hotbar slots; while one is open the
            // server reports inventory changes through it, so mirror them into window 0 (slots 9–44).
            if (container != 0 && containerSizes.TryGetValue(container, out var size) && slot >= size - 36 && slot < size)
                Put(0, slot - (size - 36) + 9, stack);
        }

        void Put(int c, int at, (int Item, int Count)? value)
        {
            if (value is { } s)
                slots[(c, at)] = s;
            else
                slots.Remove((c, at));
        }
    }

    private void TrackContent(McReader r)
    {
        var container = r.VarInt();
        lock (stateIds)
            stateIds[container] = r.VarInt();
        var n = r.VarInt();
        lock (slots)
        {
            containerSizes[container] = n;
            foreach (var key in slots.Keys.Where(k => k.Container == container).ToList())
                slots.Remove(key);
        }
        for (var i = 0; i < n; i++)
        {
            var stack = ReadStack(r);
            if (stack is null)
                return; // the rest of the packet cannot be read; those slots stay unknown
            TrackSlot(container, i, stack);
        }
    }

    private void TrackSetSlot(McReader r)
    {
        var container = r.VarInt();
        lock (stateIds)
            stateIds[container] = r.VarInt();
        var slot = r.Short();
        TrackSlot(container, slot, ReadStack(r));
    }

    private static McReader Fork(McReader r) => r.Fork();

    private void ReadRecipeBookAdd(McReader r)
    {
        var (added, replace, error) = McRecipeBook.ReadAdd(r);
        if (error is not null)
        {
            LastWorldError = error;
            if (Environment.GetEnvironmentVariable("AIJADE_MC_DUMP") is { Length: > 0 } dump)
                File.WriteAllBytes(Path.Combine(dump, "recipe-book-add.bin"), r.Payload);
        }
        lock (recipes)
        {
            if (replace)
                recipes.Clear();
            foreach (var recipe in added)
                recipes[recipe.DisplayId] = recipe;
        }
    }

    private void ReadRecipeBookRemove(McReader r)
    {
        var n = r.VarInt();
        lock (recipes)
        {
            for (var i = 0; i < n; i++)
                recipes.Remove(r.VarInt());
        }
    }

    private void ReadOpenScreen(McReader r)
    {
        var container = r.VarInt();
        r.VarInt(); // menu type; the title (a text component) follows and is not needed
        screenOpened?.TrySetResult(container);
    }

    /// <summary>Recipes in the book that make one of <paramref name="items"/>; ones that fit the inventory grid first.</summary>
    public IReadOnlyList<McRecipe> RecipesFor(IReadOnlyCollection<int> items) =>
        [.. Recipes.Where(r => r.Crafting && items.Contains(r.ResultItem)).OrderByDescending(r => r.FitsInventory).ThenBy(r => r.DisplayId)];

    /// <summary>A crafting table within <paramref name="radius"/> blocks, nearest first; null when there is none.</summary>
    public BlockPos? FindCraftingTable(int radius = 12)
    {
        var feet = Feet;
        BlockPos? best = null;
        var bestDistance = double.MaxValue;
        for (var dx = -radius; dx <= radius; dx++)
        {
            for (var dy = -4; dy <= 4; dy++)
            {
                for (var dz = -radius; dz <= radius; dz++)
                {
                    var p = feet.Offset(dx, dy, dz);
                    if (World.BlockAt(p) != CraftingTableState)
                        continue;
                    var d = (dx * dx) + (dy * dy) + (dz * dz);
                    if (d < bestDistance)
                        (best, bestDistance) = (p, d);
                }
            }
        }
        return best;
    }

    /// <summary>Right-click a crafting table within reach and wait for the server to open its screen; returns the container id.</summary>
    public async Task<int?> OpenCraftingTableAsync(BlockPos table, CancellationToken ct)
    {
        if (EyeDistance(table) > Reach + 0.5)
            throw new InvalidOperationException($"{table} is out of reach");
        await LookAtAsync(table.X + 0.5, table.Y + 0.5, table.Z + 0.5, ct).ConfigureAwait(false);
        var opened = screenOpened = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        var face = FaceTowardsEyes(table);
        await connection!.WriteAsync(SUseItemOn, new McWriter().VarInt(0).Long(table.Packed).VarInt(face).Float(0.5f).Float(0.5f).Float(0.5f).Bool(false).Bool(false)
            .VarInt(Interlocked.Increment(ref sequence)), ct).ConfigureAwait(false);
        var done = await Task.WhenAny(opened.Task, Task.Delay(TimeSpan.FromSeconds(3), ct)).ConfigureAwait(false);
        return done == opened.Task ? opened.Task.Result : null;
    }

    public Task CloseContainerAsync(int container, CancellationToken ct) =>
        connection!.WriteAsync(SContainerClose, new McWriter().VarInt(container), ct);

    private async Task<bool> WaitForResultAsync(int container, bool filled, TimeSpan timeout, CancellationToken ct)
    {
        var until = DateTimeOffset.UtcNow + timeout;
        while (DateTimeOffset.UtcNow < until)
        {
            if ((Slot(container, 0).Count > 0) == filled)
                return true;
            await Task.Delay(50, ct).ConfigureAwait(false);
        }
        return false;
    }

    /// <summary>
    /// Craft <paramref name="recipe"/> up to <paramref name="times"/> times in an open crafting container (0 = the inventory's
    /// own 2×2 grid): each round places one set of ingredients and shift-clicks the result. Stops when the grid cannot be
    /// filled (materials ran out). Returns how many rounds produced the result.
    /// </summary>
    public async Task<int> CraftAsync(McRecipe recipe, int times, int container, CancellationToken ct)
    {
        var made = 0;
        for (var i = 0; i < times; i++)
        {
            await connection!.WriteAsync(SPlaceRecipe, new McWriter().VarInt(container).VarInt(recipe.DisplayId).Bool(false), ct).ConfigureAwait(false);
            if (!await WaitForResultAsync(container, true, TimeSpan.FromSeconds(1.5), ct).ConfigureAwait(false))
                break;
            int state;
            lock (stateIds)
                state = stateIds.GetValueOrDefault(container);
            // quick move on the result slot; no predicted slots and an empty cursor: the server works it out and resyncs
            await connection.WriteAsync(SContainerClick, new McWriter().VarInt(container).VarInt(state).Short(0).Byte(0).VarInt(QuickMove).VarInt(0).Bool(false), ct).ConfigureAwait(false);
            if (!await WaitForResultAsync(container, false, TimeSpan.FromSeconds(1.5), ct).ConfigureAwait(false))
                break;
            made++;
        }
        return made;
    }
}

/// <summary>Readers for the 26.3 recipe display and slot display unions (registry order from the server's bytecode).</summary>
public static class McRecipeBook
{
    // Slot display types in registry order.
    private const int Empty = 0, AnyFuel = 1, WithAnyPotion = 2, OnlyWithComponent = 3, Item = 4, ItemStack = 5, Tag = 6, Dyed = 7,
        SmithingTrim = 8, WithRemainder = 9, Composite = 10;

    /// <summary>
    /// Recipe Book Add: entries (display id, display, group, category, optional crafting requirements, flags), then whether
    /// they replace the book. Entries carry no length, so an unreadable one ends the packet: the entries before it are kept
    /// and the error is returned.
    /// </summary>
    public static (List<McRecipe> Added, bool Replace, string? Error) ReadAdd(McReader r)
    {
        var n = r.VarInt();
        var added = new List<McRecipe>();
        try
        {
            for (var i = 0; i < n; i++)
            {
                var displayId = r.VarInt();
                var recipe = ReadDisplay(r, displayId);
                r.VarInt(); // group: optional var int (0 = none, else group + 1)
                r.VarInt(); // recipe book category
                if (r.Bool())
                {
                    var requirements = r.VarInt();
                    for (var k = 0; k < requirements; k++)
                        ReadHolderSet(r);
                }
                r.Byte(); // flags (notification, highlight)
                added.Add(recipe);
            }
            return (added, r.Bool(), null);
        }
        catch (InvalidDataException e)
        {
            return (added, false, $"recipe book: {e.Message} (kept {added.Count} of {n})");
        }
    }

    /// <summary>A holder set: VarInt n; n = 0 → a tag name follows, otherwise n − 1 registry ids. Returns the first id, if any.</summary>
    public static int? ReadHolderSet(McReader r)
    {
        var n = r.VarInt() - 1;
        if (n == -1)
        {
            r.String();
            return null;
        }
        int? first = null;
        for (var i = 0; i < n; i++)
        {
            var id = r.VarInt();
            first ??= id;
        }
        return first;
    }

    /// <summary>Read one slot display; returns the item it shows first (and the count, for stacks), or null.</summary>
    public static (int Item, int Count)? ReadSlot(McReader r)
    {
        switch (r.VarInt())
        {
            case Empty or AnyFuel:
                return null;
            case WithAnyPotion:
                return ReadSlot(r);
            case OnlyWithComponent:
            {
                var s = ReadSlot(r);
                r.VarInt(); // data component type
                return s;
            }
            case Item:
                return (r.VarInt(), 1);
            case ItemStack:
            {
                var item = r.VarInt();
                var count = r.VarInt();
                var added = r.VarInt();
                var removed = r.VarInt();
                for (var i = 0; i < added; i++)
                    SkipComponent(r);
                for (var i = 0; i < removed; i++)
                    r.VarInt();
                return (item, count);
            }
            case Tag:
                return ReadHolderSet(r) is { } id ? (id, 1) : null;
            case Dyed:
            {
                ReadSlot(r);
                return ReadSlot(r);
            }
            case SmithingTrim:
            {
                var b = ReadSlot(r);
                ReadSlot(r);
                if (r.VarInt() == 0)
                    throw new InvalidDataException("an inline trim pattern cannot be read");
                return b;
            }
            case WithRemainder:
            {
                var s = ReadSlot(r);
                ReadSlot(r);
                return s;
            }
            case Composite:
            {
                var n = r.VarInt();
                (int, int)? first = null;
                for (var i = 0; i < n; i++)
                {
                    var s = ReadSlot(r); // every element must be read, not only up to the first item
                    first ??= s;
                }
                return first;
            }
            case var t:
                throw new InvalidDataException($"unknown slot display type {t}");
        }
    }

    /// <summary>The data component type registry id of suspicious_stew_effects in 26.3 (the only component vanilla recipe results carry).</summary>
    private const int SuspiciousStewEffects = 55;

    /// <summary>
    /// Skip one added component of a recipe result. Components carry no length prefix, so only types whose layout is known
    /// can be skipped; vanilla recipe results use suspicious stew effects (a list of effect id + duration) and nothing else.
    /// </summary>
    private static void SkipComponent(McReader r)
    {
        var type = r.VarInt();
        if (type != SuspiciousStewEffects)
            throw new InvalidDataException($"a recipe result with item component {type} cannot be read");
        var n = r.VarInt();
        for (var i = 0; i < n; i++)
        {
            r.VarInt(); // effect
            r.VarInt(); // duration in ticks
        }
    }

    private static List<(int Item, int Count)?> ReadSlots(McReader r)
    {
        var n = r.VarInt();
        var list = new List<(int, int)?>(n);
        for (var i = 0; i < n; i++)
            list.Add(ReadSlot(r));
        return list;
    }

    /// <summary>Read a recipe display (type, then its fields).</summary>
    public static McRecipe ReadDisplay(McReader r, int displayId)
    {
        switch (r.VarInt())
        {
            case 0: // crafting_shapeless: ingredients, result, station
            {
                var ingredients = ReadSlots(r).Count;
                var result = ReadSlot(r);
                ReadSlot(r);
                var side = ingredients <= 1 ? 1 : ingredients <= 4 ? 2 : 3;
                return new McRecipe(displayId, result?.Item ?? -1, result?.Count ?? 0, side, side, true);
            }
            case 1: // crafting_shaped: width, height, ingredients, result, station
            {
                var width = r.VarInt();
                var height = r.VarInt();
                ReadSlots(r);
                var result = ReadSlot(r);
                ReadSlot(r);
                return new McRecipe(displayId, result?.Item ?? -1, result?.Count ?? 0, width, height, true);
            }
            case 2: // furnace: ingredient, fuel, result, station, duration, experience
            {
                ReadSlot(r);
                ReadSlot(r);
                var result = ReadSlot(r);
                ReadSlot(r);
                r.VarInt();
                r.Float();
                return new McRecipe(displayId, result?.Item ?? -1, result?.Count ?? 0, 1, 1, false);
            }
            case 3: // stonecutter: input, result, station
            {
                ReadSlot(r);
                var result = ReadSlot(r);
                ReadSlot(r);
                return new McRecipe(displayId, result?.Item ?? -1, result?.Count ?? 0, 1, 1, false);
            }
            case 4: // smithing: template, base, addition, result, station
            {
                ReadSlot(r);
                ReadSlot(r);
                ReadSlot(r);
                var result = ReadSlot(r);
                ReadSlot(r);
                return new McRecipe(displayId, result?.Item ?? -1, result?.Count ?? 0, 1, 1, false);
            }
            case var t:
                throw new InvalidDataException($"unknown recipe display type {t}");
        }
    }
}
