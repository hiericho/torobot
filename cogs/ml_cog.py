# ml_cog.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import traceback
import numpy as np
import time
from helpers import score_helper

load_dotenv()

ODDS_API_KEY = os.getenv('ODDS_API_KEY')
ODDS_API_MARKETS = 'h2h,spreads'
ODDS_API_BOOKMAKERS = 'draftkings,fanduel,betmgm,caesars,pointsbetus,epicbet'
ODDS_API_ODDS_FORMAT = 'american'

from colorama import init, Fore, Style as ColoramaStyle
init(autoreset=True)
COLOR_COG_INFO = Fore.CYAN; COLOR_COG_ERROR = Fore.RED; COLOR_COG_SUCCESS = Fore.GREEN

MAX_ODDS_API_CREDITS_PER_DAY = 320
ODDS_API_CREDITS_USED_TODAY = 0
LAST_CREDIT_RESET_DAY = datetime.now(timezone.utc).day

ODDS_CACHE = {}
CACHE_DURATION_SECONDS = 60 * 10

class MachineLearningCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self._initial_setup_lock = asyncio.Lock()
        self.initial_setup_complete = False
        self.bot.loop.create_task(self.perform_initial_model_setup())
        self.daily_credit_reset.start()

    async def cog_unload(self):
        await self.session.close()
        self.daily_credit_reset.cancel()
        print(f"{COLOR_COG_INFO}MachineLearningCog unloaded.")

    @tasks.loop(hours=1)
    async def daily_credit_reset(self):
        global ODDS_API_CREDITS_USED_TODAY, LAST_CREDIT_RESET_DAY
        now = datetime.now(timezone.utc)
        if now.day != LAST_CREDIT_RESET_DAY:
            ODDS_API_CREDITS_USED_TODAY = 0
            LAST_CREDIT_RESET_DAY = now.day
            print(f"{COLOR_COG_SUCCESS}Daily Odds API credit counter reset. Used today: 0")

    @daily_credit_reset.before_loop
    async def before_daily_credit_reset(self):
        await self.bot.wait_until_ready()
        print(f"{COLOR_COG_INFO}Daily credit reset task started.")

    async def perform_initial_model_setup(self):
        async with self._initial_setup_lock:
            if self.initial_setup_complete: return
            print(f"{ColoramaStyle.BRIGHT}{COLOR_COG_INFO}--- Cog: Starting Initial ML Model Setup ---{ColoramaStyle.RESET_ALL}")
            if not os.path.exists(score_helper.HISTORICAL_DATA_CSV):
                print(f"{COLOR_COG_ERROR}Cog: CRITICAL - Historical data CSV not found.")
                self.initial_setup_complete = True; return
            if score_helper.NBA_API_AVAILABLE:
                await self.bot.loop.run_in_executor(None, score_helper.initialize_nba_teams)
            X, y_home, y_away = await self.bot.loop.run_in_executor(None, score_helper.load_and_prep_historical_data)
            if X is not None and y_home is not None and y_away is not None:
                await self.bot.loop.run_in_executor(None, score_helper.train_all_models, X, y_home, y_away)
                if score_helper.models_store['models_ready']:
                    print(f"{COLOR_COG_SUCCESS}Cog: Models trained successfully by helper.")
                else: print(f"{COLOR_COG_ERROR}Cog: Helper reported failure to train models.")
            else:
                print(f"{COLOR_COG_ERROR}Cog: Failed to load/prep historical data. Training skipped.")
                score_helper.models_store['models_ready'] = False
            self.initial_setup_complete = True
            print(f"{ColoramaStyle.BRIGHT}{COLOR_COG_INFO}--- Cog: Initial ML Model Setup Complete. Models Ready: {score_helper.models_store['models_ready']} ---{ColoramaStyle.RESET_ALL}")

    async def get_nba_odds_data(self):
        global ODDS_API_CREDITS_USED_TODAY, ODDS_CACHE, CACHE_DURATION_SECONDS
        cache_key = "nba_odds_all_games"; current_time = time.monotonic()
        if cache_key in ODDS_CACHE:
            cached_time, cached_data = ODDS_CACHE[cache_key]
            if (current_time - cached_time) < CACHE_DURATION_SECONDS:
                print(f"{COLOR_COG_INFO}Cog: Using cached Odds API data.")
                return cached_data
        if ODDS_API_CREDITS_USED_TODAY >= MAX_ODDS_API_CREDITS_PER_DAY:
            print(f"{Fore.YELLOW}Cog: Odds API daily credit limit reached.")
            return "CREDIT_LIMIT_REACHED"
        if not ODDS_API_KEY or ODDS_API_KEY == 'YOUR_API_KEY':
            print(f"{COLOR_COG_ERROR}Cog: Odds API Key not configured."); return None
        params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': ODDS_API_MARKETS,'oddsFormat': ODDS_API_ODDS_FORMAT, 'bookmakers': ODDS_API_BOOKMAKERS, 'dateFormat': 'iso'}
        url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
        try:
            async with self.session.get(url, params=params, timeout=30) as response:
                if 200 <= response.status < 300:
                    ODDS_API_CREDITS_USED_TODAY += 1
                    print(f"{COLOR_COG_INFO}Cog: Odds API call successful. Credits used: {ODDS_API_CREDITS_USED_TODAY}/{MAX_ODDS_API_CREDITS_PER_DAY}")
                response.raise_for_status()
                data = await response.json()
                if not data: return None
                processed_games=[]
                for game in data:
                    gi={'home_team':game.get('home_team'),'away_team':game.get('away_team'),'start_time':'N/A','id':game.get('id'),'consensus_spread_point':None,'home_spread_odds':None,'away_spread_odds':None,'spread_bookie_count':0}
                    try: gi['start_time']=datetime.fromisoformat(game['commence_time'].replace('Z','+00:00')).astimezone().strftime('%a %b %d, %I:%M %p %Z')
                    except: gi['start_time']=game.get('commence_time','N/A')
                    sp=score_helper.Counter(); sdbp={}; bsc=0
                    for bookie in game.get('bookmakers',[]):
                        sm=next((m for m in bookie.get('markets',[]) if m.get('key')=='spreads'),None)
                        if sm and len(sm.get('outcomes',[]))==2:
                            bsc+=1; o=sm['outcomes']; ho=next((x for x in o if x.get('name')==game['home_team']),None); ao=next((x for x in o if x.get('name')==game['away_team']),None)
                            if ho and ao and ho.get('point') is not None:
                                pl=ho['point']; sp[pl]+=1
                                if pl not in sdbp: sdbp[pl]={'home_odds':[],'away_odds':[]}
                                if ho.get('price'): sdbp[pl]['home_odds'].append(ho['price'])
                                if ao.get('price'): sdbp[pl]['away_odds'].append(ao['price'])
                    if sp:
                        cp=sp.most_common(1)[0][0]; gi['consensus_spread_point']=cp; gi['spread_bookie_count']=bsc
                        co=sdbp.get(cp)
                        if co:
                            if co['home_odds']: gi['home_spread_odds']=int(np.mean(co['home_odds']))
                            if co['away_odds']: gi['away_spread_odds']=int(np.mean(co['away_odds']))
                    processed_games.append(gi)
                ODDS_CACHE[cache_key] = (current_time, processed_games); return processed_games
        except Exception as e: print(f"{COLOR_COG_ERROR}Cog: Error fetching odds: {e}"); traceback.print_exc(); return None

    @app_commands.command(name="machine", description="Uses machine learning to predict future scores.")
    async def machine_predict(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        async with self._initial_setup_lock: pass
        if not self.initial_setup_complete:
            await interaction.followup.send("Initial setup pending.", ephemeral=True); return
        if not score_helper.models_store['models_ready']:
            await interaction.followup.send("ML models not ready.", ephemeral=True); return
        if not score_helper.NBA_API_AVAILABLE:
            await interaction.followup.send("NBA_API not available.", ephemeral=True); return
        
        matchups_w_odds_result = await self.get_nba_odds_data()
        if matchups_w_odds_result == "CREDIT_LIMIT_REACHED":
            await interaction.followup.send(f"Odds API credit limit ({MAX_ODDS_API_CREDITS_PER_DAY}) reached.",ephemeral=True); return
        if matchups_w_odds_result is None:
            await interaction.followup.send("Could not retrieve game odds.", ephemeral=True); return
        matchups_w_odds = matchups_w_odds_result

        results_description = ""; game_count = 0; max_games_to_display = 5
        for game_data_from_odds in matchups_w_odds:
            if game_count >= max_games_to_display:
                results_description += f"\n...and {len(matchups_w_odds) - game_count} more games not shown."; break
            
            home_team_odds = game_data_from_odds['home_team']; away_team_odds = game_data_from_odds['away_team']
            match_header = f"🏀 **{away_team_odds} @ {home_team_odds}**"
            match_details = f"🕒 {game_data_from_odds.get('start_time', 'N/A')}\n"

            def process_single_game_sync_wrapper(current_game_odds):
                _h_id = score_helper.get_team_id_from_odds_name(current_game_odds['home_team'])
                _a_id = score_helper.get_team_id_from_odds_name(current_game_odds['away_team'])
                if not _h_id or not _a_id:
                    mt = current_game_odds['home_team'] if not _h_id else current_game_odds['away_team']
                    return current_game_odds, f"Team ID not found for '{mt}'"

                print(f"DEBUG COG: Processing game for Home ID: {_h_id}, Away ID: {_a_id}") # Debug
                _h_log = score_helper.get_last_n_games_for_team(_h_id)
                _a_log = score_helper.get_last_n_games_for_team(_a_id)
                if _h_log.empty or _a_log.empty:
                    reason = "home log empty" if _h_log.empty else "away log empty"
                    if _h_log.empty and _a_log.empty: reason = "both logs empty"
                    return current_game_odds, f"Failed to get sufficient game logs ({reason})"

                _h_stats = score_helper.calculate_live_rolling_stats_for_log(_h_log)
                _a_stats = score_helper.calculate_live_rolling_stats_for_log(_a_log)
                
                # --- Debug prints for stats ---
                print(f"DEBUG COG (Game: {away_team_odds} @ {home_team_odds}):")
                print(f"  Home Stats ({_h_id}): {_h_stats}")
                print(f"  Away Stats ({_a_id}): {_a_stats}")
                # --- End Debug prints ---

                # Check if stats are all NaNs, which can happen if game logs are too few or problematic
                if all(np.isnan(v) for v in _h_stats.values()) or all(np.isnan(v) for v in _a_stats.values()):
                     return current_game_odds, "Team stats consist entirely of NaNs after calculation."

                _f_vec = score_helper.prepare_live_features_from_stats(_h_stats, _a_stats)
                if _f_vec is None: return current_game_odds, "Helper failed to prepare features (None)"
                if _f_vec.isnull().values.any():
                    # print(f"DEBUG COG: Feature vector for {away_team_odds}@{home_team_odds} has NaNs before prediction:\n{_f_vec[_f_vec.isnull().any(axis=1)]}")
                    return current_game_odds, "Prepared features contain NaNs."
                
                # --- Debug print for feature vector ---
                # print(f"DEBUG COG: Feature Vector for {away_team_odds} @ {home_team_odds}:\n{_f_vec.to_string()}")
                # --- End Debug print ---

                _p_h, _p_a = score_helper.predict_scores_with_model(_f_vec, score_helper.models_store['best_model_name'])
                return current_game_odds, (_p_h, _p_a)

            processed_game_odds, result = await self.bot.loop.run_in_executor(None, process_single_game_sync_wrapper, game_data_from_odds)
            game_count += 1

            if isinstance(result, str): match_details += f"⚠️ Pred Error: {result}\n"
            elif result[0] is not None and result[1] is not None:
                ph, pa = result; ps_val = ph - pa
                ps_str = f"H {-ps_val:+.1f}" if ps_val != 0 else "PK"
                match_details += (f"Pred Score ({score_helper.models_store['best_model_name']}): **{away_team_odds} {pa} - {ph} {home_team_odds}**\nPred Spread: `{ps_str}`\n")
                bmk = score_helper.models_store['best_model_name']
                ed = score_helper.models_store.get('evaluation', {}).get(bmk, {}); bmae = ed.get('average_mae', 0) if ed else 0
                if bmae > 0: match_details += f"_(Avg. MAE: {bmae:.1f} pts)_\n"
                cs = processed_game_odds.get('consensus_spread_point')
                if cs is not None:
                    ho=processed_game_odds.get('home_spread_odds',''); ao=processed_game_odds.get('away_spread_odds','')
                    asp = -cs if cs != 0 else 0
                    ms_str = (f"Market Spread: `H {cs:+.1f} ({ho})` / `A {asp:+.1f} ({ao})` ({processed_game_odds.get('spread_bookie_count',0)} books)\n")
                    match_details += ms_str
            else: match_details += "⚠️ Pred failed (model returned None).\n"
            results_description += f"{match_header}\n{match_details}\n---\n"

        if not results_description:
            await interaction.followup.send("No predictions generated.", ephemeral=True); return
        emb_title = f"🏆 NBA ML Preds ({score_helper.models_store.get('best_model_name', 'N/A')})"
        emb_desc = results_description.strip().strip('-').strip()
        embed = discord.Embed(title=emb_title,description=emb_desc, color=discord.Color.blue(),timestamp=datetime.now(timezone.utc))
        m_maes = []
        ev = score_helper.models_store.get('evaluation', {})
        for n, ed in ev.items():
            if ed and ed.get('average_mae') is not None: m_maes.append(f"{n}: {ed['average_mae']:.2f} pts")
        if m_maes: embed.add_field(name="Model MAEs (Hist.)", value="\n".join(m_maes) if m_maes else "N/A", inline=False)
        embed.set_footer(text="Disclaimer: For info only. Scores can vary.")
        if len(embed.description) > 4096 or len(str(embed)) > 6000 :
             await interaction.followup.send("Output too long for Discord.", ephemeral=True)
        else: await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    if not os.getenv('ODDS_API_KEY'):
        print(f"{Fore.RED}ERROR: ODDS_API_KEY missing. ML Cog not added.{ColoramaStyle.RESET_ALL}"); return
    await bot.add_cog(MachineLearningCog(bot))