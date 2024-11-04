import requests
import pandas as pd
import zipfile
import os
from io import StringIO, BytesIO
import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import datetime
import calendar
import emoji

# Initialiser l'état des résultats
st.session_state.setdefault('trajet', None)

class OverpassAPI:
    def __init__(self, latitude, longitude):
        self.latitude = latitude
        self.longitude = longitude
        self.overpass_url = "http://overpass-api.de/api/interpreter"

    def fetch_cultural_places(self):
        query = f"""
        [out:json];
        (
            node["amenity"="museum"](around:1000, {self.latitude}, {self.longitude});
            way["amenity"="museum"](around:1000, {self.latitude}, {self.longitude});
            relation["amenity"="museum"](around:1000, {self.latitude}, {self.longitude});
            node["amenity"="theatre"](around:1000, {self.latitude}, {self.longitude});
            node["tourism"="art_gallery"](around:1000, {self.latitude}, {self.longitude});
            way["tourism"="art_gallery"](around:1000, {self.latitude}, {self.longitude});
            relation["tourism"="art_gallery"](around:1000, {self.latitude}, {self.longitude});
            node["historic"="castle"](around:1000, {self.latitude}, {self.longitude});
            way["historic"="castle"](around:1000, {self.latitude}, {self.longitude});
            relation["historic"="castle"](around:1000, {self.latitude}, {self.longitude});
        );
        out body;
        >;
        out skel qt;
        """

        response = requests.get(self.overpass_url, params={'data': query})
        if response.status_code == 200:
            data = response.json()
            return data['elements']
        else:
            st.error("Erreur lors de la récupération des données depuis l'API Overpass.")
            return []

    def fetch_route(self, start_node_id, end_node_id):
        query = f"""
        [out:json];
        (
          node({start_node_id});
          node({end_node_id});
          way(bn)->.a;
          (.a;>>;)->.b;
          (.a;<;)->.b;
          .b out;
        );
        out body;
        """

        response = requests.get(self.overpass_url, params={'data': query})
        if response.status_code == 200:
            data = response.json()
            nodes = data['elements']
            ways = [element for element in nodes if element['type'] == 'way']
            if ways:
                return ways[0]['nodes']
            else:
                st.error("Erreur lors de la récupération de l'itinéraire depuis l'API Overpass.")
                return []
        else:
            st.error("Erreur lors de la récupération des données depuis l'API Overpass.")
            return []

class GTFSData:
    def __init__(self, resources):
        self.resources = resources
        self.gtfs_data = {}

    def download_and_process_resources(self):
        for resource in self.resources:
            response = requests.get(resource['url'])
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type')
                if resource['format'].lower() == 'csv':
                    df = pd.read_csv(StringIO(response.text), sep=';')
                    self.gtfs_data[resource['title']] = (df, None, None, None)  # Initialiser avec des valeurs None
                elif resource['format'].lower() == 'gtfs' and 'zip' in content_type:
                    try:
                        with zipfile.ZipFile(BytesIO(response.content)) as z:
                            z.extractall(f"./gtfs/{resource['title']}")
                            self.process_gtfs_files(resource['title'])
                    except zipfile.BadZipFile:
                        st.error(f"Le fichier pour {resource['title']} n'est pas un fichier ZIP valide.")
                else:
                    st.error(f"Le format ou le type de contenu n'est pas valide pour {resource['title']}")
            else:
                st.error(f"Erreur lors du téléchargement de {resource['title']}")

    def process_gtfs_files(self, title):
        try:
            trips_df = pd.read_csv(f"./gtfs/{title}/trips.txt")
            stop_times_df = pd.read_csv(f"./gtfs/{title}/stop_times.txt")
            stops_df = pd.read_csv(f"./gtfs/{title}/stops.txt")
            routes_df = pd.read_csv(f"./gtfs/{title}/routes.txt")
            self.gtfs_data[title] = (trips_df, stop_times_df, stops_df, routes_df)
        except Exception as e:
            st.error(f"Erreur lors de la lecture des fichiers GTFS pour {title}: {e}")

    def get_trip_data(self, gare_choisie, mode_choisi):
        trajets_possibles = []
        gare_id_found = False
        lat_depart = None
        lon_depart = None

        for title, (trips_df, stop_times_df, stops_df, routes_df) in self.gtfs_data.items():
            if mode_choisi in title:
                gare_id = stops_df[stops_df['stop_name'].str.contains(gare_choisie, na=False, case=False)]

                if not gare_id.empty:
                    gare_id_found = True
                    gare_ids = gare_id['stop_id'].tolist()

                    lat_depart = gare_id['stop_lat'].values[0]
                    lon_depart = gare_id['stop_lon'].values[0]


                    departures = stop_times_df[stop_times_df['stop_id'].isin(gare_ids)]
                    
                    for index, departure in departures.iterrows():
                        trip = trips_df[trips_df['trip_id'] == departure['trip_id']]
                        if not trip.empty:
                            arrival_stop_id = stop_times_df[stop_times_df['trip_id'] == departure['trip_id']].iloc[-1]['stop_id']
                            if arrival_stop_id not in gare_ids:
                                arrival_station = stops_df[stops_df['stop_id'] == arrival_stop_id]['stop_name'].values[0]
                                arrival_lat = stops_df[stops_df['stop_id'] == arrival_stop_id]['stop_lat'].values[0]
                                arrival_lon = stops_df[stops_df['stop_id'] == arrival_stop_id]['stop_lon'].values[0]

                                route_id = trip['route_id'].values[0]
                                route_info = routes_df[routes_df['route_id'] == route_id]['route_short_name'].values[0]

                                trajets_possibles.append({
                                    'Nom': gare_choisie,
                                    'Gare d\'arrivée': arrival_station,
                                    'Latitude': arrival_lat,
                                    'Longitude': arrival_lon,
                                    'Itinéraire': route_info,
                                    'Départ Node ID': departures,
                                    'Arrivée Node ID': arrival_station
                                })

        return trajets_possibles, gare_id_found, lat_depart, lon_depart

# Liste des datasets
resources_urls = [
    {
        "title": "Gares de voyageurs du réseau ferré national",
        "url": "https://www.data.gouv.fr/fr/datasets/r/cbacca02-6925-4a46-aab6-7194debbb9b7",
        "format": "csv"
    },
    {
        "title": "Réseau national TER SNCF",
        "url": "https://eu.ftp.opendatasoft.com/sncf/gtfs/export-ter-gtfs-last.zip",
        "format": "GTFS"
    },
    {
        "title": "Réseau national TGV SNCF",
        "url": "https://eu.ftp.opendatasoft.com/sncf/gtfs/export_gtfs_voyages.zip",
        "format": "GTFS"
    },
    {
        "title": "RENFE",
        "url": "https://www.data.gouv.fr/fr/datasets/r/eae0fa46-087a-4018-ada9-d8add124e635",
        "format": "gtfs"
    },
    {
        "title": "Eurostar",
        "url": "https://www.data.gouv.fr/fr/datasets/r/9089b550-696e-4ae0-87b5-40ea55a14292",
        "format": "gtfs"
    }
]

gtfs_handler = GTFSData(resources_urls)
gtfs_handler.download_and_process_resources()

def main():
    # Interface Streamlit
    st.title('On va où ?')

    # Charger la liste des gares au démarrage
    if 'gares' not in st.session_state:
        st.session_state.gares = pd.read_csv(StringIO(requests.get(resources_urls[0]['url']).text), sep=';')['Nom'].unique().tolist()
    if 'lat_depart' not in st.session_state:
        st.session_state.lat_depart = None
    if 'lon_depart' not in st.session_state:
        st.session_state.lon_depart = None

    # Sélections utilisateur
    gare_choisie = st.selectbox('Choisissez une gare:', st.session_state.gares)
    mode_choisi = st.selectbox('Choisissez un mode de transport:', ['TGV', 'TER', 'Intercité', 'RENFE', 'Eurostar'])

    if st.button('Générer un trajet'):
        with st.spinner('Chargement des données...'):
            trajets_possibles, gare_id_found, lat_depart, lon_depart = gtfs_handler.get_trip_data(gare_choisie, mode_choisi)

            if not gare_id_found:
                st.write(f"La gare '{gare_choisie}' n'existe pas dans les données.")
            elif not trajets_possibles:
                st.write("Aucun trajet trouvé pour cette gare.")
            else:
                trajet_aleatoire = pd.DataFrame(trajets_possibles).sample(n=1).iloc[0]
                st.session_state.trajet = trajet_aleatoire  # Stocker le trajet dans l'état
                st.session_state.lat_depart = lat_depart  # Stocker les coordonnées de départ
                st.session_state.lon_depart = lon_depart  # Stocker les coordonnées de départ

    if st.session_state.trajet is not None:
        trajet_aleatoire = st.session_state.trajet
        
    # Afficher le trajet choisi
        #t.write("# Le trajet :")
        st.write(emoji.emojize(f"""### :steam_locomotive: Trajet de {trajet_aleatoire['Nom']} à {trajet_aleatoire["Gare d'arrivée"]}"""))

        # Récupérer les lieux culturels à proximité
        overpass_api = OverpassAPI(st.session_state.trajet['Latitude'], st.session_state.trajet['Longitude'])
        cultural_places = overpass_api.fetch_cultural_places()

        # Obtenir les coordonnées de la gare de départ et d'arrivée
        lat_depart = st.session_state.lat_depart
        lon_depart = st.session_state.lon_depart
        lat_arrivee = st.session_state.trajet['Latitude']
        lon_arrivee = st.session_state.trajet['Longitude']

        # Affichage de la carte à gauche et du résumé à droite

        col1 = st.columns(1)[0]

        with col1:
            # Créer la carte de l'itinéraire reliant les deux gares
            #st.write("Lat Départ : ", lat_depart, "Lon Départ : ", lon_depart, "Lat Arrivée : ", lat_arrivee, "Lon Arrivée : ", lon_arrivee)
            m_itineraire = folium.Map(location=[(lat_depart + lat_arrivee) / 2, (lon_depart + lon_arrivee) / 2], zoom_start=6)
            # Marqueur pour la gare de départ
            folium.Marker(
                [lat_depart, lon_depart],
                tooltip=trajet_aleatoire['Nom'],
                icon=folium.Icon(color='blue')
            ).add_to(m_itineraire)

            # Marqueur pour la gare d'arrivée
            folium.Marker(
                [lat_arrivee, lon_arrivee],
                tooltip=trajet_aleatoire['Gare d\'arrivée'],
                icon=folium.Icon(color='green')
            ).add_to(m_itineraire)

            # Tracer la ligne de l'itinéraire
            folium.PolyLine(
                locations=[[lat_depart, lon_depart], [lat_arrivee, lon_arrivee]],
                color='blue',
                weight=2.5,
                opacity=1
            ).add_to(m_itineraire)

            # Affichage de la carte de l'itinéraire
            st_folium(m_itineraire, width=700, height=400)

        col2, col3 = st.columns([2, 1])  # 2:1 ratio for columns

        with col2:
            # Créer la carte avec les lieux culturels
            m = folium.Map(location=[st.session_state.trajet['Latitude'], st.session_state.trajet['Longitude']], zoom_start=12)

            # Affichage des marqueurs pour les lieux culturels
            for place in cultural_places:
                if 'lat' in place and 'lon' in place:
                    tooltip = place.get('tags', {}).get('name', 'Inconnu')
                    folium.Marker([place['lat'], place['lon']], tooltip=tooltip).add_to(m)
                elif 'center' in place:
                    tooltip = place.get('tags', {}).get('name', 'Inconnu')
                    folium.Marker([place['center']['lat'], place['center']['lon']], tooltip=tooltip).add_to(m)

            # Marqueur pour la gare d'arrivée
            folium.Marker(
                [st.session_state.trajet['Latitude'], st.session_state.trajet['Longitude']],
                tooltip=st.session_state.trajet['Gare d\'arrivée'],
                icon=folium.Icon(color='green')
            ).add_to(m)

            # Affichage de la carte
            st_folium(m, width=700, height=400)

        with col3:
            # Afficher les lieux culturels à proximité de la gare d'arrivée
            st.write("Lieux culturels à proximité de la gare")
            for place in cultural_places:
                tags = place.get('tags', {})
                name = tags.get('name', None)
                if name:  # N'afficher que si le nom est connu
                    amenity = tags.get('amenity', 'Type inconnu')
                    emoji_icon = emoji.emojize(':dot:')

                    if amenity == 'musée':
                        emoji_icon = emoji.emojize(':museum:')
                    elif amenity == 'theatre':
                        emoji_icon = emoji.emojize(':performing_arts:')
                    elif amenity == 'art_gallery':
                        emoji_icon = emoji.emojize(':art:')
                    elif amenity == 'chateau':
                        emoji_icon = emoji.emojize(':castle:')
                    else:
                        emoji_icon = emoji.emojize(':star:')

                    st.write(f"{emoji_icon} {name} ({amenity})")

        # Afficher le titre au-dessus des boutons
        st.markdown(
            f"<h2 style='text-align: center;'>{emoji.emojize('Reservez votre voyage : :ticket:')}</h2>",
            unsafe_allow_html=True
        )

        # Créer les colonnes pour les boutons
        col4, col5, col6 = st.columns(3)

        with col4:
            # Ajout des boutons pour les sites externes avec style personnalisé pour SNCF
            sncf_url = "https://www.sncf-connect.com/app/home/search/od"
            st.markdown(f'''
                <a href="{sncf_url}" target="_blank">
                    <button style="background-color: black; color: rgb(50, 229, 253); padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer;">
                        SNCF Connect
                    </button>
                </a>
            ''', unsafe_allow_html=True)

        with col5:
            # Ajout du style pour le bouton "Retour au générateur"
            st.markdown(
                """
                <style>
                .orange-button {
                    background-color: rgb(241, 75, 46);
                    color: white;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                }
                </style>
                """,
                unsafe_allow_html=True
            )

            # Utilisation de st.markdown pour le bouton avec style
            st.markdown(
                """
                <a href="#" onclick="window.location.reload()">
                    <button class="orange-button">Retour au générateur</button>
                </a>
                """,
                unsafe_allow_html=True
            )

        with col6:
            # Ajout des boutons pour les sites externes avec style personnalisé pour Trainline
            trainline_url = "https://www.thetrainline.com/fr"
            st.markdown(f'''
                <a href="{trainline_url}" target="_blank">
                    <button style="background-color: rgb(54, 209, 176); color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer;">
                        Trainline
                    </button>
                </a>
            ''', unsafe_allow_html=True)

if __name__ == '__main__':
    main()