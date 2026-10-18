using Aijade.Memory.Retrieval;

namespace Aijade.Tests;

public class MemoryScoringTests
{
    [Theory]
    [InlineData("Caroline went to the LGBTQ support group", "Caroline did not go to the group", true)]
    [InlineData("Caroline went to the group", "Caroline went to the park", false)]
    [InlineData("I never eat sushi", "We don't like sushi", false)]
    [InlineData("Melanie painted in 2022", "It isn't 2022, Melanie painted in 2023", true)]
    // Known gap, kept for reproducibility of published numbers: past-tense negations ("wasn't", "weren't",
    // "haven't") are not in the cue list, so this pair is not treated as a conflict.
    [InlineData("Melanie painted in 2022", "It wasn't 2022, Melanie painted in 2023", false)]
    public void Conflict_needs_a_shared_entity_and_opposite_polarity(string a, string b, bool expected) =>
        Assert.Equal(expected, Scoring.DetectConflict(a, b));

    [Fact]
    public void Competition_ranks_average_ties()
    {
        Assert.Equal([1, 2.5, 2.5, 4], Scoring.CompetitionRanksDescending([9, 5, 5, 1]));
    }

    [Fact]
    public void Zero_variance_component_contributes_zero() =>
        Assert.All(Scoring.ZScore([0.3, 0.3, 0.3]), z => Assert.Equal(0, z));
}
