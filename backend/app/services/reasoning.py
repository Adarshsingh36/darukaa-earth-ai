from app.models.schemas import EnvironmentalInput, Recommendation

class ReasoningEngine:
    def analyze(self, e: EnvironmentalInput):
        x=e.model_dump(exclude_none=True)
        chain=[]
        recs=[]
        # Multi-metric rule 1: low SOC + low rainfall + monoculture
        if e.soil_organic_carbon is not None and e.soil_organic_carbon < 0.5 and e.rainfall_mm is not None and e.rainfall_mm < 600 and e.land_use and 'mono' in e.land_use.lower():
            chain += [
                'Low soil organic carbon can reduce aggregate stability and water-retention capacity.',
                'Low rainfall increases seasonal water stress.',
                'Monoculture provides relatively low habitat and resource diversity.',
                'Together these constraints can amplify drought stress while limiting habitat niches.'
            ]
            recs.append(('Introduce a legume cover crop during the non-crop period',
                'Adds plant-derived carbon and protects soil between crop cycles; in a low-rainfall, low-SOC system this targets soil condition and water retention while adding another plant functional group.',
                ['soil organic carbon','soil moisture retention','soil biological activity','habitat diversity'],'medium term'))
            recs.append(('Add strategically placed native tree/shrub strips or hedgerows',
                'Vegetation structure can add litter and root inputs, moderate near-surface microclimate, and create additional habitat while preserving the core cropping area.',
                ['soil organic carbon','microclimate','habitat diversity','species richness','soil moisture'],'medium to long term'))
        # Multi-metric rule 2: fragmentation + low richness
        if e.species_richness is not None and e.species_richness < 10 and e.land_use and any(k in e.land_use.lower() for k in ['fragment','isolated','intensive']):
            chain += ['Low observed species richness combined with fragmented/intensive land use suggests habitat connectivity is a constraint.']
            recs.append(('Create native habitat corridors between existing habitat patches',
                'Connecting patches can reduce isolation and provide movement and refuge resources for species; the intervention targets both habitat configuration and species support.',
                ['habitat connectivity','habitat diversity','species richness'],'medium to long term'))
        # Multi-metric rule 3: pollution + biodiversity
        if e.pollution_level == 'high' and e.species_richness is not None and e.species_richness < 15:
            chain += ['High pollution exposure alongside low species richness indicates a potential human-pressure constraint requiring source reduction and habitat recovery.']
            recs.append(('Establish vegetated buffer zones between the pollution source and sensitive habitat',
                'Buffers can intercept sediment and some pollutants while providing additional refuge and forage habitat; effectiveness depends on pollutant type and hydrology.',
                ['pollution exposure','water quality','habitat diversity','species richness'],'short to medium term'))
        return x, chain, recs
