import streamlit as st
import os
from openai import OpenAI
import json
import logging
from typing import Tuple, Dict, Any
import importlib.util

st.set_page_config(page_title="View Avocats - Obtenez une estimation grâce à l'IA", page_icon="⚖️", layout="wide")

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration du client OpenAI
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY n'est pas défini dans les variables d'environnement")

client = OpenAI(api_key=OPENAI_API_KEY)

# Chargement des modules
def load_py_module(file_path: str, module_name: str):
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        logger.error(f"Erreur lors du chargement du module {module_name}: {e}")
        return None

tarifs_module = load_py_module('./tarifs-prestations.py', 'tarifs_prestations')
instructions_module = load_py_module('./chatbot-instructions.py', 'consignes_chatbot')

# Initialisation des variables globales
tarifs = tarifs_module.get_tarifs() if tarifs_module else {}
instructions = instructions_module.get_chatbot_instructions() if instructions_module else ""

def get_openai_response(prompt: str, model: str = "gpt-3.5-turbo", num_iterations: int = 3) -> list:
    try:
        responses = []
        for _ in range(num_iterations):
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )
            content = response.choices[0].message.content.strip()
            responses.append(content)
        return responses
    except Exception as e:
        logger.error(f"Erreur lors de l'appel à l'API OpenAI: {e}")
        raise

def analyze_question(question: str, client_type: str, urgency: str) -> Tuple[str, str, float, bool]:
    options = [f"{domaine}: {', '.join(prestations_domaine.keys())}" for domaine, prestations_domaine in tarifs['prestations'].items()]
    prompt = f"""Analysez la question suivante et déterminez si elle est susceptible de concerner une thématique juridique. Si c'est fort probable, identifiez le domaine juridique et la prestation la plus pertinente, même si elle n'est pas listée dans les options fournies.

Question : {question}
Type de client : {client_type}
Degré d'urgence : {urgency}

Options de domaines et prestations (non exhaustives) :
{' '.join(options)}

Répondez au format JSON strict suivant :
{{
    "est_juridique": true/false,
    "domaine": "nom du domaine juridique",
    "prestation": "nom de la prestation",
    "indice_confiance": 0.0 à 1.0
}}
"""

    responses = get_openai_response(prompt)
    
    results = []
    for response in responses:
        try:
            result = json.loads(response)
            required_keys = ["est_juridique", "domaine", "prestation", "indice_confiance"]
            if all(key in result for key in required_keys):
                results.append(result)
            else:
                logger.warning(f"Réponse incomplète de l'API : {result}")
        except json.JSONDecodeError:
            logger.error(f"Erreur de décodage JSON dans la réponse de l'API : {response}")
    
    if not results:
        logger.warning("Aucune réponse valide de l'API")
        return "Non déterminé", "Non déterminé", 0.0, False

    is_legal = sum(r['est_juridique'] for r in results) > len(results) / 2
    domain = max(set(r['domaine'] for r in results), key=lambda x: [r['domaine'] for r in results].count(x))
    service = max(set(r['prestation'] for r in results), key=lambda x: [r['prestation'] for r in results].count(x))
    confidence = sum(r['indice_confiance'] for r in results) / len(results)
    
    # Ajuster la confiance si le domaine ou la prestation ne sont pas dans les tarifs
    if domain not in tarifs['prestations'] or service not in tarifs['prestations'].get(domain, {}):
        confidence *= 0.7  # Réduire la confiance de 30%

    is_relevant = is_legal

    return domain, service, confidence, is_relevant

def calculate_estimate(domaine: str, prestation: str, urgency: str) -> int:
    try:
        tarif_fixe = tarifs['prestations'].get(domaine, {}).get(prestation, 0)
        
        if urgency == "Urgent":
            facteur_urgence = tarifs.get("facteur_urgence", 1.5)
            tarif_fixe = round(tarif_fixe * facteur_urgence)

        return tarif_fixe
    except Exception as e:
        logger.exception(f"Erreur dans calculate_estimate: {str(e)}")
        raise

def display_loading_animation():
    return st.markdown("""
    <div style="display: flex; align-items: center; justify-content: center; flex-direction: column;">
        <svg class="loading-icon" width="50" height="50" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,1,1,1,8-8A8,8,0,0,1,12,20Z" opacity=".25"/>
            <path d="M12,4a8,8,0,0,1,7.89,6.7A1.53,1.53,0,0,0,21.38,12h0a1.5,1.5,0,0,0,1.48-1.75,11,11,0,0,0-21.72,0A1.5,1.5,0,0,0,2.62,12h0a1.53,1.53,0,0,0,1.49-1.3A8,8,0,0,1,12,4Z"/>
        </svg>
        <p style="margin-top: 10px; font-weight: bold;">Estim'IA analyse votre cas juridique...</p>
        <p>Veuillez patienter quelques secondes !</p>
    </div>
    """, unsafe_allow_html=True)

def main():
    apply_custom_css()
    
    st.title("🏛️ View Avocats - EstimiIA")

    client_type = st.selectbox("Vous êtes :", ("Particulier", "Entreprise"))
    urgency = st.selectbox("Degré d'urgence :", ("Normal", "Urgent"))
    question = st.text_area("Expliquez brièvement votre cas, notre intelligence artificielle s'occupe du reste !", height=150)

    if st.button("Obtenir une estimation grâce à l'intelligence artificielle"):
        if question:
            try:
                loading_placeholder = st.empty()
                with loading_placeholder:
                    loading_animation = display_loading_animation()
                
                domaine, prestation, confidence, is_relevant = analyze_question(question, client_type, urgency)
                
                loading_placeholder.empty()

                st.success("Analyse terminée. Voici les résultats :")
                
                domaine_info = tarifs['prestations'].get(domaine, {})
                prestation_info = domaine_info.get(prestation, {})
                
                domaine_label = domaine_info.get('label', domaine.replace('_', ' ').title())
                prestation_label = prestation_info.get('label', prestation.replace('_', ' ').title())

                col1, col2 = st.columns([2, 1])

                with col1:
                    st.subheader("Résumé de l'estimation")
                    st.write(f"**Domaine juridique :** {domaine_label}")
                    st.write(f"**Prestation :** {prestation_label}")

                with col2:
                    st.subheader("Estimation")
                    if prestation_info:
                        tarif = prestation_info.get('tarif', 'Non disponible')
                        if isinstance(tarif, (int, float)):
                            if urgency == "Urgent":
                                tarif = round(tarif * 1.5)
                            st.markdown(f"<h1 style='text-align: center; color: #1f77b4;'>À partir de<br>{tarif} €HT</h1>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<h2 style='text-align: center; color: #1f77b4;'>{tarif}</h2>", unsafe_allow_html=True)
                    else:
                        st.markdown("<h2 style='text-align: center; color: #1f77b4;'>Non disponible</h2>", unsafe_allow_html=True)
                        st.info("Cette prestation n'est pas encore répertoriée dans notre base de tarifs. Nous vous recommandons de nous contacter pour une estimation personnalisée.")

                st.markdown("---")

                st.subheader("Indice de confiance de l'analyse")
                st.progress(confidence)
                st.write(f"Confiance : {confidence:.2%}")

                if confidence < 0.5:
                    st.warning("⚠️ Attention : Notre IA a eu des difficultés à analyser votre question avec certitude. L'estimation ci-dessus peut manquer de précision.")
                elif not is_relevant:
                    st.info("Nous ne sommes pas sûr qu'il s'agisse d'une question d'ordre juridique. L'estimation ci-dessus est fournie à titre indicatif.")

                st.markdown("---")
                st.markdown("### 💡 Alternative Recommandée")
                
                consultation_initiale = tarifs['prestations']['droit_civil_contrats'].get('consultation_initiale', {})
                if consultation_initiale:
                    consultation_label = consultation_initiale.get('label', 'Consultation initiale')
                    st.info(f"**{consultation_label} d'une heure** - Tarif fixe : {consultation_initiale['tarif']} € HT")
                else:
                    st.info("Information sur la consultation initiale non disponible.")

            except Exception as e:
                st.error(f"Une erreur s'est produite : {str(e)}")
                logger.exception("Erreur dans le processus d'estimation")
        else:
            st.warning("Veuillez décrire votre cas avant de demander une estimation.")

    st.markdown("---")
    st.write("© 2024 View Avocats. Tous droits réservés.")

if __name__ == "__main__":
    main()
