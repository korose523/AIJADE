using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;

using Aijade.Integrations;
using Aijade.Integrations.Minecraft;

namespace Aijade.Tests;

public class MinecraftTests
{
    [Fact]
    public void Offline_uuids_and_varints_follow_the_protocol()
    {
        Assert.Equal(Guid.Parse("b50ad385-829d-3141-a216-7e7d7539ba7f"), McClient.OfflineUuid("Notch"));
        foreach (var (value, bytes) in new[] { (0, new byte[] { 0 }), (127, [0x7F]), (128, [0x80, 0x01]), (25565, [0xDD, 0xC7, 0x01]), (-1, [0xFF, 0xFF, 0xFF, 0xFF, 0x0F]) })
        {
            Assert.Equal(bytes, new McWriter().VarInt(value).ToArray());
            Assert.Equal(value, new McReader(bytes).VarInt());
        }
    }

    [Fact]
    public void Text_components_in_network_nbt_become_plain_text()
    {
        Assert.Equal("Steve joined the game", new McReader(Nbt.StringComponent("Steve joined the game")).TextComponent());
        // { translate: "chat.type.text", with: ["Alex", { text: "hi ", extra: ["there"] }] }
        var w = new McWriter().Byte(10)
            .Byte(8).Bytes(Name("translate")).Bytes(Str("chat.type.text"))
            .Byte(9).Bytes(Name("with")).Byte(10).Int(2)
                .Byte(8).Bytes(Name("text")).Bytes(Str("Alex")).Byte(0)
                .Byte(8).Bytes(Name("text")).Bytes(Str("hi ")).Byte(9).Bytes(Name("extra")).Byte(8).Int(1).Bytes(Str("there")).Byte(0)
            .Byte(0);
        Assert.Equal("<Alex> hi there", new McReader(w.ToArray()).TextComponent());
    }

    private static byte[] Str(string s)
    {
        var b = System.Text.Encoding.UTF8.GetBytes(s);
        return [(byte)(b.Length >> 8), (byte)b.Length, .. b];
    }

    private static byte[] Name(string s) => Str(s);

    [Fact]
    public async Task The_bot_logs_in_configures_plays_and_answers_chat_that_names_it()
    {
        var ct = TestContext.Current.CancellationToken;
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var seen = new List<ChannelMessage>();
        var bot = new MinecraftConnector("127.0.0.1", port, "Aijade").RunAsync((m, _) =>
        {
            lock (seen)
                seen.Add(m);
            return Task.FromResult<ChannelReply?>(m.AddressesBot ? new ChannelReply($"Hi {m.AuthorName}!", []) : null);
        }, cts.Token);

        using var socket = await listener.AcceptTcpClientAsync(ct);
        await using var server = new McConnection(socket.GetStream());
        async Task<McReader> Expect(int id)
        {
            var (got, r) = await server.ReadAsync(ct);
            Assert.Equal(id, got);
            return r;
        }

        var hello = await Expect(0x00);
        Assert.Equal(McClient.Protocol, hello.VarInt());
        Assert.Equal("Aijade", (await Expect(0x00)).String());
        await server.WriteAsync(0x03, new McWriter().VarInt(64), ct); // compression on from here
        server.CompressionThreshold = 64;
        await server.WriteAsync(0x02, new McWriter().Uuid(McClient.OfflineUuid("Aijade")).String("Aijade").VarInt(0), ct);
        await Expect(0x03); // login acknowledged
        await Expect(0x00); // client information
        await server.WriteAsync(0x0F, new McWriter().VarInt(0), ct);
        await Expect(0x07);
        await server.WriteAsync(0x04, new McWriter().Long(99), ct);
        Assert.Equal(99, (await Expect(0x04)).Long());
        await server.WriteAsync(0x03, new McWriter(), ct);
        await Expect(0x03); // configuration finished

        await server.WriteAsync(0x32, new McWriter().Int(1).Bool(false), ct); // login (play); the bot does not parse it
        await server.WriteAsync(0x49, new McWriter().VarInt(5).Double(1.5).Double(64).Double(-3).Double(0).Double(0).Double(0).Float(90).Float(0).Int(0), ct);
        var confirm = await Expect(0x00);
        Assert.Equal((5, 1.5, 64.0, -3.0), (confirm.VarInt(), confirm.Double(), confirm.Double(), confirm.Double()));
        await Expect(0x2C); // player loaded
        await server.WriteAsync(0x2D, new McWriter().Long(7), ct);
        Assert.Equal(7, (await Expect(0x1C)).Long());

        // A long server message (compressed on the wire) is not chat to answer; a player naming the bot is.
        await server.WriteAsync(0x7C, new McWriter().Bytes(Nbt.StringComponent(new string('=', 300))).Bool(false), ct);
        var chat = new McWriter().VarInt(0).Uuid(Guid.NewGuid()).VarInt(0).Bool(false).String("Aijade, are you there?").Long(0).Long(0).VarInt(0)
            .Bool(false).VarInt(0).VarInt(1).Bytes(Nbt.StringComponent("Steve")).Bool(false);
        await server.WriteAsync(0x42, chat, ct);
        var said = await Expect(0x09);
        Assert.Equal("Hi Steve!", said.String());
        Assert.Contains(seen, m => m.AuthorName == "Steve" && m.AddressesBot && m.Text == "Aijade, are you there?");

        await server.WriteAsync(0x20, new McWriter().Bytes(Nbt.StringComponent("Server closed")), ct);
        var ended = await Assert.ThrowsAsync<InvalidOperationException>(() => bot);
        Assert.Contains("Server closed", ended.Message, StringComparison.Ordinal);
        listener.Stop();
    }

    /// <summary>
    /// Against a real server: opt-in with AIJADE_MC_HOST / AIJADE_MC_PORT pointing at an offline-mode Java Edition 26.3 server
    /// (online-mode=false, enforce-secure-profile=false). A second protocol client plays "Steve" and talks to the companion.
    /// </summary>
    [Fact]
    public async Task On_a_real_server_the_companion_hears_a_player_and_answers_in_game()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_MC_HOST") is not { Length: > 0 } host)
        {
            Assert.Skip("AIJADE_MC_HOST is not set; real Minecraft server test skipped");
            return;
        }
        var port = int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_PORT") ?? "25565", System.Globalization.CultureInfo.InvariantCulture);
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(60));
        var heard = new TaskCompletionSource<ChannelMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
        var bot = new MinecraftConnector(host, port, "Aijade").RunAsync((m, _) =>
        {
            if (m.AddressesBot)
                heard.TrySetResult(m);
            return Task.FromResult<ChannelReply?>(m.AddressesBot ? new ChannelReply($"Hello {m.AuthorName}, I can hear you.", []) : null);
        }, cts.Token);

        await using var steve = new McClient(host, port, "Steve");
        var answered = new TaskCompletionSource<McChat>(TaskCreationOptions.RunContinuationsAsynchronously);
        var joined = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        steve.Chat += c =>
        {
            if (c.Sender == "Aijade")
                answered.TrySetResult(c);
        };
        steve.Joined += () => joined.TrySetResult();
        await steve.ConnectAsync(cts.Token);
        var play = steve.RunAsync(cts.Token);
        await joined.Task.WaitAsync(cts.Token);
        await Task.Delay(3000, cts.Token); // both players fully in the world

        await steve.SayAsync("Aijade, can you hear me?", cts.Token);
        var message = await heard.Task.WaitAsync(cts.Token);
        Assert.Equal(("Steve", "Aijade, can you hear me?"), (message.AuthorName, message.Text));
        var reply = await answered.Task.WaitAsync(cts.Token);
        Assert.Equal("Hello Steve, I can hear you.", reply.Text);

        await cts.CancelAsync();
        await Assert.ThrowsAnyAsync<Exception>(() => bot);
    }

    /// <summary>
    /// A chunk packet body as the server sends it (26.3 layout): stone in the lowest <paramref name="groundLayers"/> layers of
    /// the bottom section (an indirect 4-bit palette), every other section a single-value air container.
    /// </summary>
    internal static byte[] FlatChunk(int cx, int cz, int groundLayers = 4)
    {
        var data = new McWriter();
        for (var s = 0; s < 24; s++)
        {
            if (s == 0)
            {
                data.Bytes(new byte[] { 0x10, 0x00, 0, 0 }); // block count and fluid count (not used by the client)
                data.Byte(4).VarInt(2).VarInt(1).VarInt(0); // 4 bits, palette [stone, air]
                for (var l = 0; l < 256; l++)
                {
                    ulong word = 0;
                    for (var k = 0; k < 16; k++)
                    {
                        var index = (l * 16) + k;
                        var y = index >> 8;
                        word |= (ulong)(y < groundLayers ? 0 : 1) << (k * 4);
                    }
                    data.Long((long)word);
                }
            }
            else
            {
                data.Bytes(new byte[] { 0, 0, 0, 0 }).Byte(0).VarInt(0);
            }
            data.Byte(0).VarInt(0); // biomes: one value
        }
        var body = data.ToArray();
        return new McWriter().Int(cx).Int(cz).VarInt(0).VarInt(body.Length).Bytes(body).ToArray();
    }

    [Fact]
    public void Chunks_decode_and_paths_walk_around_walls_up_steps_and_down_drops()
    {
        var world = new McWorld();
        for (var cx = -1; cx <= 1; cx++)
        {
            for (var cz = -1; cz <= 1; cz++)
                world.LoadChunk(new McReader(FlatChunk(cx, cz)));
        }
        Assert.Equal(1, world.BlockAt(new BlockPos(0, -61, 0)));   // stone
        Assert.Equal(0, world.BlockAt(new BlockPos(0, -60, 0)));   // air above the ground
        Assert.Equal(-1, world.BlockAt(new BlockPos(100, -60, 0))); // not loaded
        var start = new BlockPos(0, -60, 0);
        Assert.True(world.CanStand(start));

        // A wall across x = 3 (two blocks high, z −4…4) forces a detour.
        for (var z = -4; z <= 4; z++)
        {
            world.SetBlock(new BlockPos(3, -60, z), 1);
            world.SetBlock(new BlockPos(3, -59, z), 1);
        }
        var around = world.FindPath(start, new BlockPos(6, -60, 0))!;
        Assert.Equal(new BlockPos(6, -60, 0), around[^1]);
        Assert.DoesNotContain(around, p => p.X == 3 && p.Z is >= -4 and <= 4);
        Assert.All(around.Zip(around.Skip(1)), step => Assert.Equal(1, Math.Abs(step.First.X - step.Second.X) + Math.Abs(step.First.Z - step.Second.Z)));

        // One block up onto a ledge, three blocks down from a tower.
        world.SetBlock(new BlockPos(-2, -60, 0), 1);
        Assert.Equal(new BlockPos(-2, -59, 0), world.FindPath(start, new BlockPos(-2, -59, 0))![^1]);
        for (var y = -60; y <= -58; y++)
            world.SetBlock(new BlockPos(0, y, 5), 1);
        Assert.NotNull(world.FindPath(new BlockPos(0, -57, 5), new BlockPos(0, -60, 7)));
        // "Near" goals stop within the radius; unreachable goals give null.
        var near = world.FindPath(start, new BlockPos(0, -60, -6), near: 2)!;
        Assert.True(Math.Abs(near[^1].Z + 6) <= 2);
        Assert.Null(world.FindPath(start, new BlockPos(10, -55, 10))); // in mid-air: nowhere to stand

        // Section updates (packed section position, VarLongs of id << 12 | local x z y) change blocks.
        var section = (0L << 42) | (0L << 20) | ((-4L) & 0xFFFFF);
        var update = new McWriter().Long(section).VarInt(1);
        long entry = (14L << 12) | (1 << 8) | (2 << 4) | 5; // cobblestone at local (1, 5, 2)
        while (true)
        {
            var b = (byte)(entry & 0x7F);
            entry >>>= 7;
            update.Byte(entry == 0 ? b : (byte)(b | 0x80));
            if (entry == 0)
                break;
        }
        world.UpdateSection(new McReader(update.ToArray()));
        Assert.Equal(14, world.BlockAt(new BlockPos(1, -59, 2)));
        Assert.Equal(new BlockPos(-5, 70, 12), BlockPos.Unpack(new BlockPos(-5, 70, 12).Packed));
        Assert.Equal(new BlockPos(30_000_000 - 1, -64, -30_000_000), BlockPos.Unpack(new BlockPos(30_000_000 - 1, -64, -30_000_000).Packed));
    }

    [Fact]
    public void Paths_swim_across_water_climb_ladders_and_avoid_lava()
    {
        static McWorld Flat()
        {
            var w = new McWorld();
            for (var cx = -1; cx <= 1; cx++)
            {
                for (var cz = -1; cz <= 1; cz++)
                    w.LoadChunk(new McReader(FlatChunk(cx, cz)));
            }
            return w;
        }
        var start = new BlockPos(0, -60, 0);

        // A channel two wide and three deep (x 3…4) across the whole loaded area: without swimming there is no way out.
        var world = Flat();
        for (var z = -16; z <= 31; z++)
        {
            for (var x = 3; x <= 4; x++)
            {
                for (var y = -63; y <= -61; y++)
                    world.SetBlock(new BlockPos(x, y, z), 89);
            }
        }
        Assert.True(world.CanStand(new BlockPos(3, -62, 0)));   // treading water
        Assert.True(world.IsSwimOrClimb(new BlockPos(3, -61, 0)));
        var across = world.FindPath(start, new BlockPos(8, -60, 0))!;
        Assert.Equal(new BlockPos(8, -60, 0), across[^1]);
        Assert.Contains(across, p => McWorld.IsWater(world.BlockAt(p)));

        // A wall four high (x −6) with a ladder column against it: the top is reached by climbing.
        world = Flat();
        for (var z = -16; z <= 31; z++)
        {
            for (var y = -60; y <= -57; y++)
                world.SetBlock(new BlockPos(-6, y, z), 1);
        }
        Assert.Null(world.FindPath(start, new BlockPos(-6, -56, 0)));
        for (var y = -60; y <= -57; y++)
            world.SetBlock(new BlockPos(-5, y, 0), 7307);
        var up = world.FindPath(start, new BlockPos(-6, -56, 0))!;
        Assert.Equal(new BlockPos(-6, -56, 0), up[^1]);
        Assert.Contains(up, p => McWorld.IsClimbable(world.BlockAt(p)) && p.Y > -60);

        // A lava moat is neither walked through nor stood on.
        world = Flat();
        for (var z = -16; z <= 31; z++)
            world.SetBlock(new BlockPos(3, -60, z), 105);
        Assert.False(world.CanStand(new BlockPos(3, -60, 0)));
        Assert.False(world.CanStand(new BlockPos(3, -59, 0)));
        Assert.Null(world.FindPath(start, new BlockPos(6, -60, 0)));
    }

    [Fact]
    public void Block_names_pick_tools_and_gear_upgrades_choose_the_best_material()
    {
        Assert.Equal("water", McBlocks.Name(89));
        Assert.Equal("lava", McBlocks.Name(105));
        Assert.Equal("ladder", McBlocks.Name(7307));
        Assert.Equal("stone", McBlocks.Name(1));
        Assert.Null(McBlocks.Name(-1));
        Assert.Equal("pickaxe", McBlocks.ToolFor("stone"));
        Assert.Equal("pickaxe", McBlocks.ToolFor("iron_ore"));
        Assert.Equal("axe", McBlocks.ToolFor("oak_log"));
        Assert.Equal("shovel", McBlocks.ToolFor("dirt"));
        Assert.Equal("hoe", McBlocks.ToolFor("oak_leaves"));
        Assert.Null(McBlocks.ToolFor("torch"));
        Assert.Equal("铁头盔", McItems.ChineseName("iron_helmet"));
        Assert.Equal("钻石镐", McItems.ChineseName("diamond_pickaxe"));
        Assert.Equal("torch", McItems.ChineseName("torch"));
        Assert.Equal("pickaxe", McGear.ToolKind("iron_pickaxe"));
        Assert.Equal("axe", McGear.ToolKind("golden_axe"));
        Assert.Null(McGear.ArmorSlot("iron_sword"));

        var inventory = new Dictionary<int, string>
        {
            [6] = "leather_chestplate", [12] = "iron_chestplate", [20] = "diamond_chestplate", [40] = "golden_helmet",
            [41] = "iron_sword", [15] = "iron_pickaxe", [38] = "stone_pickaxe", [8] = "diamond_boots", [30] = "iron_boots",
        };
        (int, int) Slot(int s) => inventory.TryGetValue(s, out var name) ? (McItems.Id(name)!.Value, 1) : (-1, 0);
        Assert.Equal([(40, 5, "golden_helmet"), (20, 6, "diamond_chestplate")], McGear.ArmorUpgrades(Slot));
        Assert.Equal(15, McGear.BestTool("pickaxe", Slot));
        Assert.Equal(41, McGear.BestTool("sword", Slot));
        Assert.Null(McGear.BestTool("shovel", Slot));
    }

    [Theory]
    [InlineData("Aijade, come here", McCommandKind.Come, false)]
    [InlineData("Aijade 过来", McCommandKind.Come, true)]
    [InlineData("follow me Aijade!", McCommandKind.Follow, false)]
    [InlineData("Aijade，跟着我", McCommandKind.Follow, true)]
    [InlineData("Aijade stop", McCommandKind.Stop, false)]
    [InlineData("Aijade 停下", McCommandKind.Stop, true)]
    [InlineData("Aijade, go to 10 -60 -3", McCommandKind.GoTo, false)]
    [InlineData("Aijade 挖 1, -61, 2", McCommandKind.Dig, true)]
    [InlineData("Aijade place a block at 4 -60 4", McCommandKind.Place, false)]
    [InlineData("Aijade, where are you?", McCommandKind.Where, false)]
    [InlineData("Aijade, pick up the stuff", McCommandKind.Collect, false)]
    [InlineData("Aijade 捡起来", McCommandKind.Collect, true)]
    [InlineData("Aijade, attack that pig", McCommandKind.Attack, false)]
    [InlineData("Aijade 打僵尸", McCommandKind.Attack, true)]
    [InlineData("Aijade, craft 4 sticks", McCommandKind.Craft, false)]
    [InlineData("Aijade 做两个木棍", McCommandKind.Craft, true)]
    [InlineData("Aijade, put on your armor", McCommandKind.Equip, false)]
    [InlineData("Aijade, gear up", McCommandKind.Equip, false)]
    [InlineData("Aijade 穿上盔甲", McCommandKind.Equip, true)]
    public void Commands_are_recognised_in_english_and_chinese(string text, McCommandKind kind, bool chinese)
    {
        var command = MinecraftBehaviour.Parse(text, "Aijade")!;
        Assert.Equal((kind, chinese), (command.Kind, command.Chinese));
        if (kind is McCommandKind.GoTo or McCommandKind.Dig or McCommandKind.Place)
            Assert.NotNull(command.At);
    }

    [Theory]
    [InlineData("Aijade, how are you?")]
    [InlineData("Aijade, let's go somewhere nice")] // "go" without coordinates is conversation
    [InlineData("Aijade, I love to build things")]
    [InlineData("Aijade, let's hit the road")] // attack needs a creature the companion knows
    [InlineData("Aijade 你在做什么")] // "做" without an item is conversation
    [InlineData("Aijade, make me laugh")]
    public void Ordinary_chat_is_not_a_command(string text) => Assert.Null(MinecraftBehaviour.Parse(text, "Aijade"));

    [Theory]
    [InlineData("Aijade, craft 4 sticks", "stick", 4)]
    [InlineData("Aijade 做两个木棍", "stick", 2)]
    [InlineData("Aijade, make a crafting table", "crafting_table", 1)]
    [InlineData("Aijade, make a wooden pickaxe", "wooden_pickaxe", 1)]
    [InlineData("Aijade 合成工作台", "crafting_table", 1)]
    public void Craft_commands_name_the_item_and_the_quantity(string text, string item, int count)
    {
        var command = MinecraftBehaviour.Parse(text, "Aijade")!;
        Assert.Equal(McCommandKind.Craft, command.Kind);
        Assert.Equal([McItems.Id(item)!.Value], command.Items);
        Assert.Equal(count, command.Count);
        // a family: every kind of planks
        Assert.Contains(McItems.Id("oak_planks")!.Value, MinecraftBehaviour.Parse("Aijade, make some planks", "Aijade")!.Items);
    }

    [Fact]
    public void The_recipe_book_reads_shaped_and_shapeless_displays()
    {
        static int Id(string n) => McItems.Id(n)!.Value;
        var w = new McWriter().VarInt(2);
        // crafting table: shaped 2×2 of the planks tag, result one table, station the table; group none; category; requirements
        w.VarInt(17).VarInt(1).VarInt(2).VarInt(2).VarInt(4);
        for (var i = 0; i < 4; i++)
            w.VarInt(6).VarInt(0).String("minecraft:planks");
        w.VarInt(5).VarInt(Id("crafting_table")).VarInt(1).VarInt(0).VarInt(0) // result: item stack
            .VarInt(4).VarInt(Id("crafting_table"))                               // station: item
            .VarInt(0).VarInt(3).Bool(true).VarInt(1).VarInt(3).VarInt(Id("oak_planks")).VarInt(Id("spruce_planks")).Byte(0);
        // oak planks: shapeless from a direct holder set of logs, four planks; in a group
        w.VarInt(42).VarInt(0).VarInt(1).VarInt(6).VarInt(2).VarInt(Id("oak_log"))
            .VarInt(5).VarInt(Id("oak_planks")).VarInt(4).VarInt(0).VarInt(0)
            .VarInt(4).VarInt(Id("crafting_table"))
            .VarInt(5).VarInt(3).Bool(false).Byte(1);
        w.Bool(true);
        var r = new McReader(w.ToArray());
        var (added, replace, error) = McRecipeBook.ReadAdd(r);
        Assert.Null(error);
        Assert.True(replace);
        Assert.True(r.AtEnd);
        Assert.Equal(new McRecipe(17, Id("crafting_table"), 1, 2, 2, true), added[0]);
        Assert.Equal(new McRecipe(42, Id("oak_planks"), 4, 1, 1, true), added[1]);
        Assert.All(added, x => Assert.True(x.FitsInventory));
        // a result with components cannot be read: the entries before it are kept
        var bad = new McWriter().VarInt(2);
        bad.VarInt(1).VarInt(0).VarInt(0).VarInt(4).VarInt(Id("stick")).VarInt(4).VarInt(Id("crafting_table")).VarInt(0).VarInt(0).Bool(false).Byte(0);
        bad.VarInt(2).VarInt(0).VarInt(0).VarInt(5).VarInt(Id("stick")).VarInt(1).VarInt(1).VarInt(0).VarInt(7); // component 7: layout unknown
        var (partial, _, why) = McRecipeBook.ReadAdd(new McReader(bad.ToArray()));
        Assert.Single(partial);
        Assert.Contains("component 7", why);
        // a composite display is read to its end (all elements), and suspicious stew's effects are skipped
        var stew = new McWriter().VarInt(1)
            .VarInt(9).VarInt(0).VarInt(1).VarInt(10).VarInt(2).VarInt(4).VarInt(Id("red_mushroom")).VarInt(4).VarInt(Id("brown_mushroom"))
            .VarInt(5).VarInt(Id("suspicious_stew")).VarInt(1).VarInt(1).VarInt(0).VarInt(55).VarInt(1).VarInt(11).VarInt(60)
            .VarInt(4).VarInt(Id("crafting_table")).VarInt(0).VarInt(2).Bool(false).Byte(0).Bool(false);
        var sr = new McReader(stew.ToArray());
        var (stewed, _, none) = McRecipeBook.ReadAdd(sr);
        Assert.Null(none);
        Assert.True(sr.AtEnd);
        Assert.Equal(Id("suspicious_stew"), stewed[0].ResultItem);
    }

    [Fact]
    public async Task On_a_real_server_the_companion_crafts_from_its_recipe_book()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_MC_HOST") is not { Length: > 0 } host
            || Environment.GetEnvironmentVariable("AIJADE_MC_RCON_PASSWORD") is not { Length: > 0 } rcon)
        {
            Assert.Skip("AIJADE_MC_HOST / AIJADE_MC_RCON_PASSWORD are not set; real Minecraft crafting test skipped");
            return;
        }
        var port = int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_PORT") ?? "25565", System.Globalization.CultureInfo.InvariantCulture);
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(120));
        await using var console = new Aijade.Server.Tools.RconClient(host, int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_RCON_PORT") ?? "25575", System.Globalization.CultureInfo.InvariantCulture), rcon);
        await using var bot = new McClient(host, port, "Aijade");
        using var behaviour = new MinecraftBehaviour(bot);
        await bot.ConnectAsync(cts.Token);
        var play = bot.RunAsync(cts.Token);
        async Task Until(Func<bool> condition, string what, int seconds = 20)
        {
            var until = DateTimeOffset.UtcNow.AddSeconds(seconds);
            while (!condition())
            {
                if (play.IsFaulted)
                    throw new InvalidOperationException($"the client stopped while waiting for: {what}", play.Exception!.InnerException);
                Assert.True(DateTimeOffset.UtcNow < until, $"timed out waiting for: {what} (last world error: {bot.LastWorldError})");
                await Task.Delay(100, cts.Token);
            }
        }
        await Until(() => bot.World.CanStand(bot.Feet), "standing in loaded chunks");
        var here = bot.Feet;
        // a table left behind by an earlier, interrupted run would make the "no table nearby" step meaningless
        await console.ExecuteAsync($"fill {here.X - 14} {here.Y - 4} {here.Z - 14} {here.X + 14} {here.Y + 4} {here.Z + 14} minecraft:air replace minecraft:crafting_table", cts.Token);
        await Until(() => bot.FindCraftingTable() is null, "no crafting table nearby");
        await console.ExecuteAsync("clear Aijade", cts.Token);
        await console.ExecuteAsync("recipe give Aijade *", cts.Token);
        await Until(() => bot.RecipesFor([McItems.Id("wooden_pickaxe")!.Value]).Count > 0, "the recipe book");
        await console.ExecuteAsync("give Aijade minecraft:oak_log 4", cts.Token);
        int Count(string item) => bot.CountInInventory(McItems.Id(item)!.Value);
        await Until(() => Count("oak_log") == 4, "four logs in the inventory");

        async Task<string> Run(string text)
        {
            var said = new ConcurrentQueue<string>();
            await behaviour.RunAsync(MinecraftBehaviour.Parse(text, "Aijade")!, null, s =>
            {
                said.Enqueue(s);
                return Task.CompletedTask;
            }, cts.Token);
            return string.Join(" | ", said);
        }
        // the inventory's own 2×2 grid
        Assert.Equal("Made 12 oak planks.", await Run("Aijade, craft 12 oak planks"));
        await Until(() => Count("oak_planks") == 12 && Count("oak_log") == 1, $"12 planks and 1 log (have {Count("oak_planks")} / {Count("oak_log")})");
        Assert.Equal("Made 4 stick.", await Run("Aijade, make 4 sticks"));
        Assert.Equal("Made 1 crafting table.", await Run("Aijade, make a crafting table"));
        await Until(() => Count("stick") == 4 && Count("crafting_table") == 1 && Count("oak_planks") == 6, "sticks, table and the planks left");
        // a 3×3 recipe needs a crafting table: none nearby yet…
        Assert.Equal("I need a crafting table nearby to make wooden pickaxe.", await Run("Aijade, make a wooden pickaxe"));
        // …so the console puts one next to the companion
        var spot = bot.Feet.Offset(2, 0, 0);
        await console.ExecuteAsync($"setblock {spot.X} {spot.Y} {spot.Z} minecraft:crafting_table", cts.Token);
        await Until(() => bot.World.BlockAt(spot) == McClient.CraftingTableState, "the table in the world");
        Assert.Equal("Made 1 wooden pickaxe.", await Run("Aijade, make a wooden pickaxe"));
        await Until(() => Count("wooden_pickaxe") == 1 && Count("oak_planks") == 3 && Count("stick") == 2, $"the pickaxe (planks {Count("oak_planks")}, sticks {Count("stick")})");
        Assert.Equal("I don't have the materials for bucket.", await Run("Aijade, make a bucket"));

        await console.ExecuteAsync($"setblock {spot.X} {spot.Y} {spot.Z} minecraft:air", cts.Token);
        await console.ExecuteAsync("clear Aijade", cts.Token);
        await cts.CancelAsync();
        await Assert.ThrowsAnyAsync<Exception>(() => play);
    }

    [Fact]
    public async Task On_a_real_server_the_companion_puts_on_armour_and_digs_with_the_right_tool()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_MC_HOST") is not { Length: > 0 } host
            || Environment.GetEnvironmentVariable("AIJADE_MC_RCON_PASSWORD") is not { Length: > 0 } rcon)
        {
            Assert.Skip("AIJADE_MC_HOST / AIJADE_MC_RCON_PASSWORD are not set; real Minecraft equipment test skipped");
            return;
        }
        var port = int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_PORT") ?? "25565", System.Globalization.CultureInfo.InvariantCulture);
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(120));
        await using var console = new Aijade.Server.Tools.RconClient(host, int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_RCON_PORT") ?? "25575", System.Globalization.CultureInfo.InvariantCulture), rcon);
        await using var bot = new McClient(host, port, "Aijade");
        using var behaviour = new MinecraftBehaviour(bot);
        await bot.ConnectAsync(cts.Token);
        var play = bot.RunAsync(cts.Token);
        async Task Until(Func<bool> condition, string what, int seconds = 20)
        {
            var until = DateTimeOffset.UtcNow.AddSeconds(seconds);
            while (!condition())
            {
                if (play.IsFaulted)
                    throw new InvalidOperationException($"the client stopped while waiting for: {what}", play.Exception!.InnerException);
                Assert.True(DateTimeOffset.UtcNow < until, $"timed out waiting for: {what} (last world error: {bot.LastWorldError})");
                await Task.Delay(100, cts.Token);
            }
        }
        async Task<string> Run(string text)
        {
            var said = new ConcurrentQueue<string>();
            await behaviour.RunAsync(MinecraftBehaviour.Parse(text, "Aijade")!, null, s =>
            {
                said.Enqueue(s);
                return Task.CompletedTask;
            }, cts.Token);
            return string.Join(" | ", said);
        }
        string? Worn(int armorSlot) => bot.Slot(0, armorSlot) is { Item: >= 0 } s ? McItems.Name(s.Item) : null;

        await Until(() => bot.World.CanStand(bot.Feet), "standing in loaded chunks");
        await console.ExecuteAsync("gamemode survival Aijade", cts.Token);
        await console.ExecuteAsync("clear Aijade", cts.Token);
        await Until(() => Enumerable.Range(5, 40).All(s => bot.Slot(0, s).Item < 0), "an empty inventory after clearing");
        Assert.Equal("I have no better armour to put on.", await Run("Aijade, put on your armor"));

        // a weak chestplate worn first, then a better one and a helmet in the main inventory
        await console.ExecuteAsync("item replace entity Aijade armor.chest with minecraft:leather_chestplate", cts.Token);
        await console.ExecuteAsync("item replace entity Aijade inventory.3 with minecraft:iron_chestplate", cts.Token);
        await console.ExecuteAsync("item replace entity Aijade inventory.10 with minecraft:golden_helmet", cts.Token);
        await Until(() => Worn(6) == "leather_chestplate" && bot.CountInInventory(McItems.Id("iron_chestplate")!.Value) == 1, "the armour in place");
        Assert.Equal("Now wearing golden helmet, iron chestplate.", await Run("Aijade, put on your armor"));
        await Until(() => Worn(5) == "golden_helmet" && Worn(6) == "iron_chestplate", $"armour worn (head {Worn(5)}, chest {Worn(6)})");
        Assert.Equal(1, bot.CountInInventory(McItems.Id("leather_chestplate")!.Value));
        Assert.Equal("我身上没有更好的盔甲可以换。", await Run("Aijade 穿上盔甲"));

        // a stone block next to the companion: the pickaxe in the main inventory is swapped into the hand to dig it
        await console.ExecuteAsync("item replace entity Aijade inventory.5 with minecraft:iron_pickaxe", cts.Token);
        await Until(() => bot.CountInInventory(McItems.Id("iron_pickaxe")!.Value) == 1, "the pickaxe");
        var block = bot.Feet.Offset(1, 0, 0);
        await console.ExecuteAsync($"setblock {block.X} {block.Y} {block.Z} minecraft:stone", cts.Token);
        await Until(() => bot.World.BlockAt(block) == 1, "the stone in the world");
        Assert.Equal("iron_pickaxe", await bot.HoldToolForAsync(block, cts.Token));
        await Until(() => McItems.Name(bot.Slot(0, 36 + bot.SelectedSlot).Item) == "iron_pickaxe", "the pickaxe in the hand");

        await console.ExecuteAsync($"setblock {block.X} {block.Y} {block.Z} minecraft:air", cts.Token);
        await console.ExecuteAsync("clear Aijade", cts.Token);
        await cts.CancelAsync();
        await Assert.ThrowsAnyAsync<Exception>(() => play);
    }

    [Fact]
    public async Task On_a_real_server_the_companion_swims_across_water_and_climbs_a_ladder()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_MC_HOST") is not { Length: > 0 } host
            || Environment.GetEnvironmentVariable("AIJADE_MC_RCON_PASSWORD") is not { Length: > 0 } rcon)
        {
            Assert.Skip("AIJADE_MC_HOST / AIJADE_MC_RCON_PASSWORD are not set; real Minecraft swimming test skipped");
            return;
        }
        var port = int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_PORT") ?? "25565", System.Globalization.CultureInfo.InvariantCulture);
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(120));
        await using var console = new Aijade.Server.Tools.RconClient(host, int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_RCON_PORT") ?? "25575", System.Globalization.CultureInfo.InvariantCulture), rcon);
        await using var bot = new McClient(host, port, "Aijade");
        await bot.ConnectAsync(cts.Token);
        var play = bot.RunAsync(cts.Token);
        async Task Until(Func<bool> condition, string what, int seconds = 20)
        {
            var until = DateTimeOffset.UtcNow.AddSeconds(seconds);
            while (!condition())
            {
                if (play.IsFaulted)
                    throw new InvalidOperationException($"the client stopped while waiting for: {what}", play.Exception!.InnerException);
                Assert.True(DateTimeOffset.UtcNow < until, $"timed out waiting for: {what} (last world error: {bot.LastWorldError})");
                await Task.Delay(100, cts.Token);
            }
        }
        Task Run(string command) => console.ExecuteAsync(command, cts.Token);
        await Until(() => bot.World.BlockAt(bot.Feet) >= 0, "the chunks around the companion");
        // put back at the end, so that the other tests find the companion where they left it (on its feet, should an earlier
        // run have left it stuck in a block)
        var feet = bot.Feet;
        var rise = 0;
        while (rise < 4 && !bot.World.CanStand(feet.Offset(0, rise, 0)))
            rise++;
        var home = (bot.Position.X, Y: (double)feet.Y + rise, bot.Position.Z);
        // an area of its own, rebuilt to the flat world's layers (bedrock, two dirt, grass) and cleared above, so that what
        // an earlier, interrupted run left behind cannot change the terrain
        var f = new BlockPos(400, -60, 400);
        await Run($"tp Aijade {f.X + 0.5} {f.Y} {f.Z + 0.5}");
        await Until(() => bot.Feet == f && bot.World.CanStand(f), $"standing on the test area (at {bot.Feet})");
        await Run($"fill {f.X - 4} {f.Y - 4} {f.Z - 30} {f.X + 7} {f.Y - 4} {f.Z + 30} minecraft:bedrock");
        await Run($"fill {f.X - 4} {f.Y - 3} {f.Z - 30} {f.X + 7} {f.Y - 2} {f.Z + 30} minecraft:dirt");
        await Run($"fill {f.X - 4} {f.Y - 1} {f.Z - 30} {f.X + 7} {f.Y - 1} {f.Z + 30} minecraft:grass_block");
        await Run($"fill {f.X - 4} {f.Y} {f.Z - 30} {f.X + 7} {f.Y + 5} {f.Z + 30} minecraft:air");
        await Until(() => McWorld.IsAir(bot.World.BlockAt(f.Offset(-3, 0, 0))) && McWorld.IsSolid(bot.World.BlockAt(f.Offset(2, -1, 0))), "the rebuilt area");

        // a channel two wide and three deep across x + 2…3: the only way over is to swim
        await Run($"fill {f.X + 2} {f.Y - 3} {f.Z - 30} {f.X + 3} {f.Y - 1} {f.Z + 30} minecraft:water");
        await Until(() => McWorld.IsWater(bot.World.BlockAt(new BlockPos(f.X + 2, f.Y - 1, f.Z))), "the channel in the world");
        var across = f.Offset(6, 0, 0);
        Assert.Contains(bot.World.FindPath(bot.Feet, across)!, p => McWorld.IsWater(bot.World.BlockAt(p)));
        Assert.True(await bot.GoToAsync(across, 0, cts.Token), $"could not swim across (at {bot.Feet})");
        Assert.Equal(across, bot.Feet);

        // a wall four high at x − 3 with a ladder on its east face: up by climbing, back down the same way
        await Run($"fill {f.X - 3} {f.Y} {f.Z - 30} {f.X - 3} {f.Y + 3} {f.Z + 30} minecraft:stone");
        await Run($"fill {f.X - 2} {f.Y} {f.Z} {f.X - 2} {f.Y + 3} {f.Z} minecraft:ladder[facing=east]");
        await Until(() => McWorld.IsClimbable(bot.World.BlockAt(new BlockPos(f.X - 2, f.Y + 3, f.Z))), "the ladder in the world");
        var top = new BlockPos(f.X - 3, f.Y + 4, f.Z);
        Assert.True(await bot.GoToAsync(top, 0, cts.Token), $"could not climb (at {bot.Feet})");
        Assert.Equal(top, bot.Feet);
        Assert.True(await bot.GoToAsync(f, 0, cts.Token), $"could not climb down (at {bot.Feet})");
        Assert.Equal(f, bot.Feet);

        await Run($"fill {f.X - 3} {f.Y} {f.Z - 30} {f.X - 2} {f.Y + 3} {f.Z + 30} minecraft:air");
        await Run($"fill {f.X + 2} {f.Y - 3} {f.Z - 30} {f.X + 3} {f.Y - 2} {f.Z + 30} minecraft:dirt");
        await Run($"fill {f.X + 2} {f.Y - 1} {f.Z - 30} {f.X + 3} {f.Y - 1} {f.Z + 30} minecraft:grass_block");
        await Run(string.Create(System.Globalization.CultureInfo.InvariantCulture, $"tp Aijade {home.X} {home.Y} {home.Z}"));
        await Until(() => Math.Abs(bot.Position.X - home.X) < 0.01 && Math.Abs(bot.Position.Z - home.Z) < 0.01, "back where it started");
        await cts.CancelAsync();
        await Assert.ThrowsAnyAsync<Exception>(() => play);
    }

    [Fact]
    public async Task On_a_real_server_the_companion_comes_digs_places_and_follows()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_MC_HOST") is not { Length: > 0 } host)
        {
            Assert.Skip("AIJADE_MC_HOST is not set; real Minecraft server test skipped");
            return;
        }
        var port = int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_PORT") ?? "25565", System.Globalization.CultureInfo.InvariantCulture);
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(180));

        await using var bot = new McClient(host, port, "Aijade");
        using var behaviour = new MinecraftBehaviour(bot);
        bot.Chat += chat =>
        {
            if (chat.Sender is { } sender && sender != "Aijade" && MinecraftBehaviour.Parse(chat.Text, "Aijade") is { } command)
                _ = behaviour.RunAsync(command, chat.SenderId, text => bot.SayAsync(text, cts.Token), cts.Token);
        };
        await using var steve = new McClient(host, port, "Steve");
        var said = new ConcurrentQueue<string>();
        steve.Chat += c =>
        {
            if (c.Sender == "Aijade")
                said.Enqueue(c.Text);
        };
        await bot.ConnectAsync(cts.Token);
        var botPlay = bot.RunAsync(cts.Token);
        await steve.ConnectAsync(cts.Token);
        var stevePlay = steve.RunAsync(cts.Token);

        async Task Until(Func<bool> condition, string what, int seconds = 30)
        {
            var until = DateTimeOffset.UtcNow.AddSeconds(seconds);
            while (!condition())
            {
                foreach (var play in new[] { botPlay, stevePlay })
                {
                    if (play.IsFaulted)
                        throw new InvalidOperationException($"a client stopped while waiting for: {what}", play.Exception!.InnerException);
                }
                Assert.True(DateTimeOffset.UtcNow < until, $"timed out waiting for: {what}; Aijade said: {string.Join(" | ", said)}");
                await Task.Delay(100, cts.Token);
            }
        }
        double Apart() => Math.Sqrt(Math.Pow(bot.Position.X - steve.Position.X, 2) + Math.Pow(bot.Position.Z - steve.Position.Z, 2));
        async Task Ask(string text, string expectedReply)
        {
            await steve.SayAsync(text, cts.Token);
            await Until(() => said.Any(s => s.StartsWith(expectedReply, StringComparison.Ordinal)), $"reply \"{expectedReply}\" to \"{text}\"");
            said.Clear();
        }

        await Until(() => bot.World.CanStand(bot.Feet) && steve.World.CanStand(steve.Feet), "both players standing in loaded chunks");
        await Until(() => bot.World.EntityByUuid(McClient.OfflineUuid("Steve")) is not null, "Aijade sees Steve");

        // Steve walks away; the companion tracks where he is (entity movement packets)…
        var away = bot.Feet.X > steve.Feet.X ? -8 : 8; // away from the companion, so that coming needs a real walk
        Assert.True(await steve.GoToAsync(steve.Feet.Offset(away, 0, 3), 0, cts.Token), "Steve could not walk");
        Assert.True(Apart() > 6, $"the players are only {Apart():0.0} blocks apart");
        McEntity Seen() => bot.World.EntityByUuid(McClient.OfflineUuid("Steve"))!;
        await Until(() => Math.Abs(Seen().X - steve.Position.X) < 0.5 && Math.Abs(Seen().Z - steve.Position.Z) < 0.5,
            $"Aijade's view of Steve to match his position (seen {Seen().X:0.0} {Seen().Y:0.0} {Seen().Z:0.0}, actual {steve.Position.X:0.0} {steve.Position.Y:0.0} {steve.Position.Z:0.0})", 10);
        // …and, asked to come, finds a path and arrives next to him.
        await Ask("Aijade, come here", "Coming!");
        await Until(() => said.Any(s => s == "Here I am."), "arrival");
        Assert.True(Apart() <= 3.2, $"Aijade stopped {Apart():0.0} blocks away");
        said.Clear();

        // Digging a ground block: Steve's own client sees the block update, and the companion picks up what drops…
        // (on the side away from Steve, who would otherwise pick up the drop himself)
        var ground = new[] { (2, 0), (-2, 0), (0, 2), (0, -2) }.Select(d => bot.Feet.Offset(d.Item1, -1, d.Item2))
            .OrderByDescending(p => Math.Pow(p.X + 0.5 - steve.Position.X, 2) + Math.Pow(p.Z + 0.5 - steve.Position.Z, 2)).First();
        Assert.True(McWorld.IsSolid(steve.World.BlockAt(ground)));
        Assert.All(bot.Hotbar, c => Assert.True(c >= 0, "the hotbar should be readable (plain items only)"));
        var held = bot.Hotbar.Sum(); // the server keeps players' inventories between runs
        await Ask($"Aijade, dig {ground}", "Dug out");
        await Until(() => McWorld.IsAir(steve.World.BlockAt(ground)), "Steve's client to see the block dug out", 5);
        await Until(() => bot.Hotbar.Sum() == held + 1, $"the dug block in the companion's hotbar (held {held}, now {bot.Hotbar.Sum()})");

        // …and puts it back: placing uses whatever block it holds.
        await Ask($"Aijade, place {ground}", "Placed a block");
        await Until(() => McWorld.IsSolid(steve.World.BlockAt(ground)), "Steve's client to see the block placed", 5);

        // Attacking: the local test server's console puts a pig next to the companion.
        if (Environment.GetEnvironmentVariable("AIJADE_MC_RCON_PASSWORD") is { Length: > 0 } rcon)
        {
            await using var console = new Aijade.Server.Tools.RconClient(host, int.Parse(Environment.GetEnvironmentVariable("AIJADE_MC_RCON_PORT") ?? "25575", System.Globalization.CultureInfo.InvariantCulture), rcon);
            var spot = bot.Feet.Offset(3, 0, 0);
            await console.ExecuteAsync($"summon minecraft:pig {spot.X} {spot.Y} {spot.Z}", cts.Token);
            await Until(() => bot.World.Entities(101).Count > 0, "Aijade sees the pig");
            await steve.SayAsync("Aijade, attack the pig", cts.Token);
            await Until(() => said.Any(s => s == "The pig is gone."), "the pig defeated", 60);
            said.Clear();
        }

        await Ask("Aijade, where are you?", "I'm at");

        // Following: Steve walks off; the companion keeps up until told to stop.
        await Ask("Aijade, follow me", "Following you.");
        Assert.True(await steve.GoToAsync(steve.Feet.Offset(-4, 0, -9), 0, cts.Token), "Steve could not walk");
        await Until(() => Apart() <= 3.5, "Aijade catching up");
        await Ask("Aijade, stop", "Stopping.");
        await cts.CancelAsync();
        await Assert.ThrowsAnyAsync<Exception>(() => botPlay);
        await Assert.ThrowsAnyAsync<Exception>(() => stevePlay);
    }
}
