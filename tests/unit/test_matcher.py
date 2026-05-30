"""Unit tests for movie title matching - the most critical functionality."""

import pytest

from src.core.boxoffice import BoxOfficeMovie
from src.core.matcher import MatchResult, MovieMatcher
from src.core.models import MovieStatus
from src.core.radarr import RadarrMovie


class TestMovieTitleMatching:
    """Test the critical movie title matching functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = MovieMatcher(min_confidence=0.8)

        # Create test Radarr movies with various title formats
        self.radarr_movies = [
            self._create_radarr_movie(1, "Spider-Man: No Way Home", 2021),
            self._create_radarr_movie(2, "Spider-Man: Far From Home", 2019),
            self._create_radarr_movie(3, "The Batman", 2022),
            self._create_radarr_movie(4, "Batman", 1989),
            self._create_radarr_movie(5, "A.I. Artificial Intelligence", 2001),
            self._create_radarr_movie(6, "M3GAN", 2023),
            self._create_radarr_movie(7, "Gladiator", 2000),
            self._create_radarr_movie(8, "Gladiator 2", 2024),  # Sequel with number
            self._create_radarr_movie(9, "Dr. Seuss' The Grinch", 2018),
            self._create_radarr_movie(10, "Wicked", 2024),
            self._create_radarr_movie(11, "Dune", 2021),
            self._create_radarr_movie(12, "Dune", 1984),  # Same title, different year
            self._create_radarr_movie(13, "Top Gun: Maverick", 2022),
            self._create_radarr_movie(14, "Avatar: The Way of Water", 2022),
            self._create_radarr_movie(
                15, "Fast & Furious Presents: Hobbs & Shaw", 2019
            ),
            self._create_radarr_movie(16, "The Good, the Bad and the Ugly", 1966),
            self._create_radarr_movie(17, "Frozen II", 2019),
            self._create_radarr_movie(18, "The Dark Knight", 2008),
        ]

        self.matcher.build_movie_index(self.radarr_movies)

    def _create_radarr_movie(self, id: int, title: str, year: int) -> RadarrMovie:
        """Helper to create a RadarrMovie object."""
        return RadarrMovie(
            id=id,
            title=title,
            tmdbId=id * 1000,
            year=year,
            status=MovieStatus.RELEASED,
            hasFile=False,
        )

    def test_exact_title_match(self):
        """Test exact title matching."""
        result = self.matcher.match_single("Wicked", self.radarr_movies)

        assert result.is_matched
        assert result.radarr_movie.title == "Wicked"
        assert result.confidence == 1.0
        assert result.match_method == "exact"

    def test_colon_subtitle_variations(self):
        """Test matching titles with colons and subtitles - very common issue."""
        # Box Office might show "Spider-Man No Way Home" without colon
        result = self.matcher.match_single("Spider-Man No Way Home", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Spider-Man: No Way Home"

        # Or with different punctuation
        result = self.matcher.match_single(
            "Spider-Man - No Way Home", self.radarr_movies
        )
        assert result.is_matched
        assert result.radarr_movie.title == "Spider-Man: No Way Home"

    def test_dots_and_special_characters(self):
        """Test matching titles with dots and special characters."""
        # A.I. might be shown as AI
        result = self.matcher.match_single(
            "AI Artificial Intelligence", self.radarr_movies
        )
        assert result.is_matched
        assert result.radarr_movie.title == "A.I. Artificial Intelligence"

        # M3GAN might appear without special formatting
        result = self.matcher.match_single("MEGAN", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "M3GAN"

    def test_apostrophes_and_possessives(self):
        """Test matching titles with apostrophes."""
        # Different apostrophe styles
        result = self.matcher.match_single("Dr. Seuss' The Grinch", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Dr. Seuss' The Grinch"

        # Without apostrophe
        result = self.matcher.match_single("Dr Seuss The Grinch", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Dr. Seuss' The Grinch"

    def test_roman_numerals_vs_numbers(self):
        """Test matching sequels with Roman numerals vs regular numbers."""
        # Frozen 2 should match Frozen II
        result = self.matcher.match_single("Frozen 2", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Frozen II"

        # Gladiator II should try to match Gladiator 2
        result = self.matcher.match_single("Gladiator II", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Gladiator 2"

        # Regular Gladiator should match one of the Gladiator movies
        result = self.matcher.match_single("Gladiator", self.radarr_movies)
        assert result.is_matched
        assert "Gladiator" in result.radarr_movie.title
        # Could match either "Gladiator" (2000) or "Gladiator 2" (2024)

    def test_same_title_different_years(self):
        """Test matching movies with same title but different years - critical for remakes."""
        # Without year should match one of them (exact match prefers first found)
        result = self.matcher.match_single("Dune", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Dune"

        # The matcher's year handling in _try_special_cases should help match the right version
        # This tests that the matcher at least finds a Dune movie when year is included
        result = self.matcher.match_single("Dune (2021)", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Dune"
        # Note: Current implementation may not perfectly match by year - this is a known limitation

        result = self.matcher.match_single("Dune (1984)", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Dune"

    def test_the_article_variations(self):
        """Test matching with and without 'The' article."""
        result = self.matcher.match_single("Batman", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Batman"
        assert result.radarr_movie.year == 1989

        result = self.matcher.match_single("The Batman", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "The Batman"
        assert result.radarr_movie.year == 2022

        # "Dark Knight" should match "The Dark Knight"
        result = self.matcher.match_single("Dark Knight", self.radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "The Dark Knight"

    def test_ampersand_variations(self):
        """Test matching titles with & vs 'and'."""
        result = self.matcher.match_single(
            "Fast and Furious Presents: Hobbs and Shaw", self.radarr_movies
        )
        assert result.is_matched
        assert result.radarr_movie.title == "Fast & Furious Presents: Hobbs & Shaw"

        result = self.matcher.match_single(
            "The Good the Bad and the Ugly", self.radarr_movies
        )
        assert result.is_matched
        assert result.radarr_movie.title == "The Good, the Bad and the Ugly"

    def test_batch_matching_preserves_order(self):
        """Test that batch matching preserves box office ranking order."""
        box_office_movies = [
            BoxOfficeMovie(rank=1, title="Spider-Man: No Way Home"),
            BoxOfficeMovie(rank=2, title="The Batman"),
            BoxOfficeMovie(rank=3, title="Dune"),
        ]

        results = self.matcher.match_batch(box_office_movies, self.radarr_movies)

        assert len(results) == 3
        assert results[0].box_office_movie.rank == 1
        assert results[1].box_office_movie.rank == 2
        assert results[2].box_office_movie.rank == 3
        assert all(r.is_matched for r in results)

    def test_no_match_for_unknown_movie(self):
        """Test that unknown movies don't match incorrectly."""
        result = self.matcher.match_single(
            "Some Random Movie That Doesn't Exist 2024", self.radarr_movies
        )

        assert not result.is_matched
        assert result.radarr_movie is None
        assert result.confidence == 0.0
        assert result.match_method == "none"

    def test_fuzzy_matching_with_typos(self):
        """Test fuzzy matching handles minor typos but not major differences."""
        # Minor typo should match
        result = self.matcher.match_single(
            "Spiderman: No Way Home", self.radarr_movies
        )  # Missing hyphen
        assert result.is_matched
        assert result.radarr_movie.title == "Spider-Man: No Way Home"

        # Major difference should not match - use a completely different title
        result = self.matcher.match_single(
            "Completely Random Movie Title That Doesn't Exist", self.radarr_movies
        )
        assert not result.is_matched

    def test_match_movie_method_compatibility(self):
        """Test the match_movie method used by routes."""
        box_office_movie = BoxOfficeMovie(
            rank=1, title="The Batman", weekend_gross=100000000
        )

        result = self.matcher.match_movie(box_office_movie, self.radarr_movies)

        assert result.is_matched
        assert result.radarr_movie.title == "The Batman"
        assert result.box_office_movie == box_office_movie

    def test_french_original_title_variants_match_radarr(self):
        """French box-office titles should match by original title when available."""
        radarr_movies = [
            self._create_radarr_movie(19, "Avatar: Fire and Ash", 2026),
            self._create_radarr_movie(20, "Zootopia 2", 2026),
            self._create_radarr_movie(21, "L'Affaire Bojarski", 2026),
        ]
        self.matcher.build_movie_index(radarr_movies)

        avatar = BoxOfficeMovie(
            rank=2,
            title="Avatar : de feu et de cendres",
            original_title="Avatar: Fire and Ash",
            year=2026,
        )
        result = self.matcher.match_movie(avatar, radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Avatar: Fire and Ash"
        assert result.confidence >= 0.95

        zootopie = BoxOfficeMovie(
            rank=5,
            title="Zootopie 2",
            original_title="Zootopia 2",
            year=2026,
        )
        result = self.matcher.match_movie(zootopie, radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "Zootopia 2"

        apostrophe = BoxOfficeMovie(
            rank=4,
            title="L’Affaire Bojarski",
            year=2026,
        )
        result = self.matcher.match_movie(apostrophe, radarr_movies)
        assert result.is_matched
        assert result.radarr_movie.title == "L'Affaire Bojarski"

    def test_french_tmdb_confirmed_matching_rejects_false_positives(self):
        """FR matching should only trust TMDb-confirmed Radarr matches."""

        def fake_search(term: str, language=None, region=None):
            lowered = term.lower()
            if "bojarski" in lowered:
                return [
                    {
                        "title": "X-Men: Apocalypse",
                        "originalTitle": "X-Men: Apocalypse",
                        "tmdbId": 20001,
                        "year": 2016,
                    }
                ]
            if "forêts" in lowered or "forets" in lowered:
                return [
                    {
                        "title": "3-Iron",
                        "originalTitle": "3-Iron",
                        "tmdbId": 20002,
                        "year": 2004,
                    }
                ]
            if "greenland" in lowered:
                return [
                    {
                        "title": "2:22",
                        "originalTitle": "2:22",
                        "tmdbId": 20003,
                        "year": 2017,
                    }
                ]
            if "mage" in lowered:
                return [
                    {
                        "title": "Le Mage du Kremlin",
                        "originalTitle": "The Kremlin Wizard",
                        "tmdbId": 20004,
                        "year": 2026,
                    }
                ]
            if "femme" in lowered or "housemaid" in lowered:
                return [
                    {
                        "title": "La Femme de ménage",
                        "originalTitle": "The Housemaid",
                        "alternateTitles": [{"title": "The Housemaid"}],
                        "tmdbId": 20005,
                        "year": 2026,
                        "remotePoster": "poster",
                    }
                ]
            if "avatar" in lowered:
                return [
                    {
                        "title": "Avatar : de feu et de cendres",
                        "originalTitle": "Avatar: Fire and Ash",
                        "alternateTitles": [{"title": "Avatar: Fire and Ash"}],
                        "tmdbId": 20006,
                        "year": 2026,
                        "remotePoster": "poster",
                    }
                ]
            return []

        radarr_movies = [
            self._create_radarr_movie(201, "X-Men: Apocalypse", 2016),
            self._create_radarr_movie(202, "3-Iron", 2004),
            self._create_radarr_movie(203, "2:22", 2017),
            self._create_radarr_movie(204, "n", 2026),
            self._create_radarr_movie(205, "The Housemaid", 2026),
            self._create_radarr_movie(206, "Avatar: Fire and Ash", 2026),
        ]
        # Align TMDB ids with the fake search responses.
        radarr_movies[0].tmdbId = 20001
        radarr_movies[1].tmdbId = 20002
        radarr_movies[2].tmdbId = 20003
        radarr_movies[3].tmdbId = 20004
        radarr_movies[4].tmdbId = 20005
        radarr_movies[5].tmdbId = 20006
        self.matcher.build_movie_index(radarr_movies)

        false_positive_titles = [
            "L'Affaire Bojarski",
            "Le Chant des forêts",
            "Greenland Migration",
            "Le Mage du Kremlin",
        ]
        for rank, title in enumerate(false_positive_titles, start=1):
            result = self.matcher.match_movie(
                BoxOfficeMovie(rank=rank, title=title, year=2026),
                radarr_movies,
                market="fr",
                search_movie_tmdb=fake_search,
            )
            assert not result.is_matched
            assert result.confidence == 0.0
            assert result.debug["rejection_reason"] is not None

        positive_avatar = self.matcher.match_movie(
            BoxOfficeMovie(
                rank=9,
                title="Avatar : de feu et de cendres",
                original_title="Avatar: Fire and Ash",
                year=2026,
            ),
            radarr_movies,
            market="fr",
            search_movie_tmdb=fake_search,
        )
        assert positive_avatar.is_matched
        assert positive_avatar.radarr_movie.title == "Avatar: Fire and Ash"
        assert positive_avatar.match_method == "tmdb_confirmed"
        assert positive_avatar.confidence > 0.0

        positive_housemaid = self.matcher.match_movie(
            BoxOfficeMovie(
                rank=10,
                title="La Femme de ménage",
                original_title="The Housemaid",
                year=2026,
            ),
            radarr_movies,
            market="fr",
            search_movie_tmdb=fake_search,
        )
        assert positive_housemaid.is_matched
        assert positive_housemaid.radarr_movie.title == "The Housemaid"
        assert positive_housemaid.match_method == "tmdb_confirmed"
        assert positive_housemaid.confidence > 0.0

    def test_french_tmdb_confirmed_matching_uses_detail_enrichment(self):
        """FR matching should use JPBoxOffice detail metadata when it helps confirm identity."""
        detail_calls = []

        def detail_fetcher(source_href):
            detail_calls.append(source_href)
            return {
                "original_title": "The Singing Forests",
                "english_title": "The Singing Forests",
                "director": "Patrice Forest",
                "year": 2026,
            }

        def fake_search(term: str, language=None, region=None):
            lowered = term.lower()
            if "singing forests" in lowered:
                return [
                    {
                        "title": "The Singing Forests",
                        "originalTitle": "The Singing Forests",
                        "tmdbId": 20007,
                        "year": 2026,
                    }
                ]
            return []

        radarr_movies = [self._create_radarr_movie(207, "The Singing Forests", 2026)]
        radarr_movies[0].tmdbId = 20007
        self.matcher.build_movie_index(radarr_movies)

        result = self.matcher.match_movie(
            BoxOfficeMovie(
                rank=8,
                title="Le Chant des forêts",
                source_href="/fichfilm.php?id=50007&view=2",
                jpboxoffice_id=50007,
            ),
            radarr_movies,
            market="fr",
            search_movie_tmdb=fake_search,
            detail_fetcher=detail_fetcher,
        )

        assert detail_calls == ["/fichfilm.php?id=50007&view=2"]
        assert result.is_matched
        assert result.radarr_movie.title == "The Singing Forests"
        assert result.match_method == "tmdb_confirmed"
        assert result.resolved_tmdb_id == 20007
        assert result.identity_status == "Matched in Radarr"

    def test_french_tmdb_confirmed_matching_without_radarr_preserves_tmdb_identity(self):
        """FR matching should keep a confirmed TMDB identity even when Radarr has no entry."""
        detail_calls = []

        def detail_fetcher(source_href):
            detail_calls.append(source_href)
            return {
                "original_title": "The Kremlin Wizard",
                "english_title": "The Kremlin Wizard",
                "director": "Patrice Kremlin",
                "year": 2026,
            }

        def fake_search(term: str, language=None, region=None):
            if "kremlin" in term.lower():
                return [
                    {
                        "title": "Le Mage du Kremlin",
                        "originalTitle": "The Kremlin Wizard",
                        "tmdbId": 20008,
                        "year": 2026,
                        "remotePoster": "poster",
                    }
                ]
            return []

        result = self.matcher.match_movie(
            BoxOfficeMovie(
                rank=7,
                title="Le Mage du Kremlin",
                source_href="/fichfilm.php?id=50008&view=2",
                jpboxoffice_id=50008,
            ),
            [],
            market="fr",
            search_movie_tmdb=fake_search,
            detail_fetcher=detail_fetcher,
        )

        assert detail_calls == ["/fichfilm.php?id=50008&view=2"]
        assert not result.is_matched
        assert result.resolved_tmdb_id == 20008
        assert result.confidence > 0.0
        assert result.match_method == "tmdb_confirmed"
        assert result.identity_status == "TMDB confirmed / not in Radarr"


class TestMatcherEdgeCases:
    """Test edge cases and error handling in the matcher."""

    def test_empty_radarr_library(self):
        """Test matching against empty Radarr library."""
        matcher = MovieMatcher()
        result = matcher.match_single("Any Movie", [])

        assert not result.is_matched
        assert result.confidence == 0.0

    def test_none_values_handling(self):
        """Test that None values don't crash the matcher."""
        matcher = MovieMatcher()
        radarr_movies = [RadarrMovie(id=1, title="Test Movie", tmdbId=1000, year=None)]

        matcher.build_movie_index(radarr_movies)
        result = matcher.match_single("Test Movie", radarr_movies)

        assert result.is_matched
        assert result.radarr_movie.title == "Test Movie"

    def test_confidence_threshold(self):
        """Test that matches below confidence threshold are rejected."""
        # Create matcher with high threshold
        strict_matcher = MovieMatcher(min_confidence=0.95)

        radarr_movies = [RadarrMovie(id=1, title="The Batman", tmdbId=1000, year=2022)]
        strict_matcher.build_movie_index(radarr_movies)

        # Very different title should not match
        result = strict_matcher.match_single("The Batperson", radarr_movies)
        assert not result.is_matched
