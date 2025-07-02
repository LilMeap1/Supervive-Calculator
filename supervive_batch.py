from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
import gspread
from google.oauth2.service_account import Credentials
import json
import time
import sys
import re
import hashlib
import shutil
import urllib.parse

TEAM_FILE = "teams.json"


def load_teams():
    try:
        with open(TEAM_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print("⚠️ Warning: Could not load teams.json. Using empty fallback.")
        return {}

teams = load_teams() 
team_mappings = {} 



json_key_file = ""  # KEY FILE REMOVED FOR REPO PURPOSES
spreadsheet_name = "Supervive Scrims"
base_team_row = 3  

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_file(json_key_file, scopes=scope)
gc = gspread.auth.service_account(filename=json_key_file)
worksheet = gc.open(spreadsheet_name).sheet1
spreadsheet = gc.open(spreadsheet_name)
stats_sheet = spreadsheet.worksheet("Stats")

options = webdriver.ChromeOptions()
options.add_argument("--headless") 
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

print("✅ Chrome is running !")


print("Received arguments:", sys.argv)

time.sleep(20)

def process_past_games(num_games):
    global team_mappings

    driver.get(opgg_link)
    time.sleep(5)

    while True:
        match_containers = driver.find_elements(By.CLASS_NAME, "space-y-2")
        if len(match_containers) >= 6:
            break
        print("⚠️ Could not locate the match history block. Waiting...")
        time.sleep(3)

    match_history_block = match_containers[5]
    past_games = match_history_block.find_elements(By.XPATH, "./div")

    if not past_games:
        print("⚠️ No games found.")
        return [], []

    print(f"🔍 Found {len(past_games)} total games. Searching for last {num_games} Custom Games...")

    processed_teams_data = []
    all_stats_data = []
    team_mappings.clear()
    custom_games_found = 0

    for i in range(len(past_games)):
        if custom_games_found >= num_games:
            break

        try:
            game = past_games[i]

            custom_game_label = game.find_elements(
                By.XPATH, ".//div[contains(@class, 'text-xs font-bold text-red-500')]"
            )

            if not custom_game_label or "Custom Game" not in custom_game_label[0].text:
                print(f"❌ Game {i+1} is NOT a Custom Game. Skipping...")
                continue

            print(f"✅ Game {i+1} is a Custom Game. Processing...")

            try:
                dropdown_button = game.find_element(By.XPATH, ".//button[contains(@class, 'items-center')]")
                dropdown_button.click()
                print(f"✅ Clicked dropdown for Custom Game #{custom_games_found + 1}.")
                time.sleep(5)
            except Exception as e:
                print(f"⚠️ Could not click dropdown for Game {i+1}: {e}")
                continue

            teams_data = extract_team_data(game)

            if custom_games_found == 0:
                teams_data = assign_team_names(teams_data)

            formatted_teams_data = {}
            for team_number, team_info in teams_data.items():
                team_tag = team_mappings.get(team_number, team_number)
                formatted_teams_data[team_tag] = {
                    "placement": team_info["placement"],
                    "kills": team_info["kills"]
                }
                for player in team_info["players"]:
                    all_stats_data.append([
                        custom_games_found + 1,
                        player["name"],
                        player["kills"],
                        player["deaths"],
                        player["assists"],
                        player["hunter"]
                    ])

            processed_teams_data.append(formatted_teams_data)
            custom_games_found +=1

            print(f"✅ Processed Custom Game #{custom_games_found}")

        except Exception as e:
            print(f"⚠️ Error processing Game #{i+1}: {e}")

    print(f"✅ Completed batch processing. Processed {custom_games_found} Custom Games.")
    return processed_teams_data, all_stats_data


def open_game_dropdown(game_block):
    """ Click the dropdown to expose team data. """
    while True:
        try:
            dropdown_button = game_block.find_element(
                By.XPATH, ".//button[contains(@class, 'items-center')]"
            )
            dropdown_button.click()
            print("✅ Clicked dropdown.")
            time.sleep(5)  
            break
        except Exception as e:
            print(f"⚠️ Failed to click dropdown. Retrying... {e}")
            time.sleep(3)

def extract_team_data(latest_game):
    """ Extracts team placements, Team #X, total kills, and player-level data including Hunter. """
    teams_data = {}

    try:
        team_blocks = latest_game.find_elements(
            By.XPATH, ".//div[contains(@class, 'rounded') and contains(@class, 'border-opacity')]"
        )

        print(f"🟢 Found {len(team_blocks)} team blocks. Processing...")

        retry_attempts = 0
        while len(team_blocks) == 0:
            retry_attempts += 1
            print(f"⚠️ No team blocks found. Retrying (attempt {retry_attempts})...")
            time.sleep(5)
            team_blocks = latest_game.find_elements(
                By.XPATH,
                ".//div[contains(@class, 'rounded') and contains(@class, 'border-opacity')]"
            )

        for team in team_blocks:
            try:
                team_number_element = team.find_element(
                    By.XPATH, ".//div[@class='text-muted-foreground']"
                )
                team_number = team_number_element.text.strip()
                print(f"📌 Found {team_number} in team block.")

                try:
                    placement_element = team.find_element(
                        By.XPATH,
                        ".//div[contains(@class, 'flex items-center gap-2')]/div[contains(@class, 'font-bold')]"
                    )
                    placement = placement_element.text.strip()
                    print(f"🏆 Placement for {team_number}: {placement}")
                except:
                    placement = "Unknown"
                    print(f"⚠️ Could not find placement for {team_number}.")

                team_players = []
                try:
                    player_rows = team.find_elements(
                        By.XPATH, ".//div[contains(@class, 'flex items-center justify-between rounded w-full')]"
                    )

                    for row in player_rows:
                        try:
                            player_name_element = row.find_element(
                                By.XPATH, ".//div[contains(@class, 'text-xs cursor-help')]"
                            )
                            player_name = player_name_element.text.strip().split("#")[0]

                            stats_text = row.text.strip()
                            kda_match = re.search(r'(\d+)/(\d+)/(\d+)', stats_text)
                            kills = int(kda_match.group(1)) if kda_match else 0
                            deaths = int(kda_match.group(2)) if kda_match else 0
                            assists = int(kda_match.group(3)) if kda_match else 0

                            hunter_name = "Unknown"
                            try:
                                hunter_block = row.find_element(
                                    By.XPATH,
                                    ".//div[contains(@class, 'flex items-center gap-2')]//div[contains(@class, 'text-md') and contains(@class, 'font-bold')]"
                                )
                                hunter_name = hunter_block.text.strip()
                            except Exception:
                                print(f"⚠️ No hunter found for {player_name}")

                            team_players.append({
                                "name": player_name,
                                "kills": kills,
                                "deaths": deaths,
                                "assists": assists,
                                "hunter": hunter_name
                            })

                            print(f"👤 {player_name} | {kills}/{deaths}/{assists} | Hunter: {hunter_name}")
                        except Exception:
                            print("⚠️ Could not extract full player row.")

                except Exception as e:
                    print(f"⚠️ Error extracting player names: {e}")

                total_kills = sum(player["kills"] for player in team_players)

                teams_data[team_number] = {
                    "placement": placement,
                    "kills": total_kills,
                    "players": team_players
                }

                print(f"✅ Stored {team_number}: Placement: {placement}, Kills: {total_kills}, Players: {[p['name'] for p in team_players]}")

            except Exception as e:
                print(f"❌ Error processing a team block: {e}")

    except Exception as e:
        print(f"⚠️ Error extracting team data: {e}")

    return teams_data


def assign_team_names(teams_data):
    """ Assigns correct team names using the majority rule on first detection and persists for future games. """
    global team_mappings

    print("🔄 Assigning team names based on player priority rule.")

    for team_number, data in teams_data.items():
        if team_number in team_mappings:

            teams_data[team_number]["team_name"] = team_mappings[team_number]
            print(f"🔁 Reused previous mapping: {team_number} → {team_mappings[team_number]}")
            continue


        player_team_counts = {}

        print(f"\n📌 Processing {team_number}: Players: {data['players']}")

        for team_name, team_info in teams.items():
            for player in data["players"]:
                if player["name"] in team_info["players"]:
                    if team_name not in player_team_counts:
                        player_team_counts[team_name] = 0
                    if player["name"] == team_info["captain"]:
                        player_team_counts[team_name] += 3  
                        print(f"⭐ {player} is a Captain of {team_name} (+3 points)")
                    else:
                        player_team_counts[team_name] += 2 
                        print(f"🔹 {player} is a Member of {team_name} (+2 points)")


        if player_team_counts:
            best_team = max(player_team_counts, key=player_team_counts.get)
            print(f"✅ Assigned {team_number} to {best_team} with {player_team_counts[best_team]} points")
            team_mappings[team_number] = best_team  
            teams_data[team_number]["team_name"] = best_team 

    return teams_data



def update_spreadsheet(processed_games_data):
        """ Updates Google Sheets with the latest game results using team tags, ensuring newest games are on the right. """

        total_games = len(processed_games_data)  
        print(f"🔄 Updating spreadsheet with {total_games} games in reverse order...")


        column_positions = {
            10:["T", "U"],
            9: ["R", "S"],
            8: ["P", "Q"],
            7: ["N", "O"],
            6: ["L", "M"],  
            5: ["J", "K"], 
            4: ["H", "I"],  
            3: ["F", "G"],  
            2: ["D", "E"],  
            1: ["B", "C"]   
        }


        latest_game_data = processed_games_data[0]  
        placement_column, kills_column = column_positions[total_games]  

        existing_teams = worksheet.col_values(1)
        batch_updates = []


        for i, (team_tag, team_info) in enumerate(latest_game_data.items()):
            team_row = base_team_row + i  
            batch_updates.append({"range": f"A{team_row}", "values": [[team_tag]]})
            
            formatted_placement = f"{team_info['placement']} Place"
            batch_updates.append({"range": f"{placement_column}{team_row}", "values": [[formatted_placement]]})
            batch_updates.append({"range": f"{kills_column}{team_row}", "values": [[team_info['kills']]]})


        worksheet.batch_update(batch_updates)
        print(f"✅ Game 1 updated at {placement_column}, {kills_column}")


        time.sleep(3)


        batch_updates = []  
        for game_index in range(1, total_games):
            game_data = processed_games_data[game_index]
            placement_column, kills_column = column_positions[total_games - game_index] 

            print(f"📝 Preparing batch update for Game {game_index + 1} → Columns: {placement_column}, {kills_column}")

            existing_teams = worksheet.col_values(1)  

            for team_tag, team_info in game_data.items():
                try:
                    if team_tag in existing_teams:
                        team_row = existing_teams.index(team_tag) + 1  
                    else:
                        print(f"⚠️ Could not find {team_tag} in Column A for Game {game_index + 1}. Skipping...")
                        continue

                    formatted_placement = f"{team_info['placement']} Place"
                    batch_updates.append({"range": f"{placement_column}{team_row}", "values": [[formatted_placement]]})
                    batch_updates.append({"range": f"{kills_column}{team_row}", "values": [[team_info['kills']]]})

                except Exception as e:
                    print(f"❌ Error preparing update for {team_tag}: {e}")


        if batch_updates:
            worksheet.batch_update(batch_updates)
            print("✅ Batch update sent for Games 2+ in reverse order.")
        else:
            print("⚠️ No updates queued for Games 2+.")

        print("✅ Spreadsheet update complete.")

def update_stats_worksheet(all_stats_data):
    """Updates the 'Stats' sheet with all player stat rows, including team TAGs."""
    if not all_stats_data:
        print("⚠️ No stats data to write.")
        return

    print(f"📊 Preparing to write {len(all_stats_data)} player stat entries to 'Stats' worksheet...")

    base_row = 3

    column_map = {
        "game_num": "B",
        "player_name": "D",
        "tag": "F",
        "kills": "H",
        "deaths": "J",
        "assists": "L",
        "hunter": "N"
    }

    def find_tag(player_name):
        for tag, data in teams.items():
            if player_name in data.get("players", []):
                return tag
        return ""

    updates = []

    for idx, stat in enumerate(all_stats_data):
        row = base_row + idx
        game_num, name, kills, deaths, assists, hunter = stat
        tag = find_tag(name)

        updates.append({"range": f"{column_map['game_num']}{row}", "values": [[game_num]]})
        updates.append({"range": f"{column_map['player_name']}{row}", "values": [[name]]})
        updates.append({"range": f"{column_map['tag']}{row}", "values": [[tag]]})
        updates.append({"range": f"{column_map['kills']}{row}", "values": [[kills]]})
        updates.append({"range": f"{column_map['deaths']}{row}", "values": [[deaths]]})
        updates.append({"range": f"{column_map['assists']}{row}", "values": [[assists]]})
        updates.append({"range": f"{column_map['hunter']}{row}", "values": [[hunter]]})

    stats_sheet.batch_update(updates)
    print("✅ Stats worksheet updated successfully.")


def build_opgg_link(username):
    """
    Builds a supervive.op.gg profile link for a given username.
    Spaces are converted to %20, # to %23, etc.
    Example: 'Tom Kick#TTV' → 'https://supervive.op.gg/players/steam-Tom%20Kick%23TTV'
    """
    encoded = urllib.parse.quote(username)
    return f"https://supervive.op.gg/players/steam-{encoded}"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("⚠️ Usage: python supervive_batch.py <number_of_games> <username>")
        sys.exit(1)

    num_games = int(sys.argv[1])
    username = sys.argv[2].strip('"')

    opgg_link = build_opgg_link(username)

    print(f"🔄 Processing the past {num_games} Custom Games for `{username}` ({opgg_link})...")

    driver.get(opgg_link)
    time.sleep(5)

    processed_games_data, all_stats_data = process_past_games(num_games)

    print(f"DEBUG: Processed games data → {processed_games_data}")
    print(f"DEBUG: Total player stats rows → {len(all_stats_data)}")

    if processed_games_data:
        print("✅ Calling update_spreadsheet() to log team data...")
        update_spreadsheet(processed_games_data)

        print("✅ Calling update_stats_worksheet() to log player stats...")
        update_stats_worksheet(all_stats_data)
    else:
        print("⚠️ No valid game data found. Skipping spreadsheet updates.")

    print(f"✅ Completed batch processing for `{username}`.")


